import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from snowflake.snowpark import Session

st.set_page_config(
    page_title="COVID-19 OWID Dashboard",
    page_icon="🌍",
    layout="wide"
)

connection_parameters = {
    "user": st.secrets["snowflake"]["user"],
    "password": st.secrets["snowflake"]["password"],
    "account": st.secrets["snowflake"]["account"],
    "warehouse": st.secrets["snowflake"]["warehouse"],
    "database": st.secrets["snowflake"].get("database", "TEST_DB"),
    "schema": st.secrets["snowflake"].get("schema", "PUBLIC"),
    "role": st.secrets["snowflake"]["role"],
}

TABLE_NAME = "COVID_OWID_DATA"
DATA_URL = "https://raw.githubusercontent.com/owid/covid-19-data/master/public/data/owid-covid-data.csv"
FILTER_COUNTRIES = [
    "Brazil",
    "United States",
    "India",
    "Germany",
    "South Africa",
    "Japan",
]

def load_filtered_data(url: str) -> pd.DataFrame:
    """Baixa o CSV da OWID e aplica os filtros de país e data."""
    df = pd.read_csv(url)
    df = df[df["location"].isin(FILTER_COUNTRIES)]
    df = df[df["date"] >= "2021-01-01"]
    return df


def create_snowflake_session() -> Session:
    """Cria a sessão Snowpark e garante warehouse/database/schema ativos."""
    session = Session.builder.configs(connection_parameters).create()

    try:
        session.sql(f"USE WAREHOUSE {connection_parameters['warehouse']}").collect()
    except Exception as e:
        session.close()
        raise RuntimeError(
            f"Falha ao usar o WAREHOUSE '{connection_parameters['warehouse']}'. "
            "Verifique se ele existe e se a role tem permissão USAGE. "
            f"Erro original: {e}"
        )

    try:
        session.sql(f"USE DATABASE {connection_parameters['database']}").collect()
    except Exception as e:
        session.close()
        raise RuntimeError(
            f"Falha ao usar o DATABASE '{connection_parameters['database']}'. "
            "Verifique se ele existe e se a role tem permissão USAGE. "
            f"Erro original: {e}"
        )

    try:
        session.sql(f"USE SCHEMA {connection_parameters['schema']}").collect()
    except Exception as e:
        session.close()
        raise RuntimeError(
            f"Falha ao usar o SCHEMA '{connection_parameters['schema']}'. "
            "Verifique se ele existe no database e se a role tem permissão USAGE. "
            f"Erro original: {e}"
        )

    return session


def upload_to_snowflake(df: pd.DataFrame, table_name: str) -> None:
    """Envia o DataFrame filtrado para uma tabela no Snowflake."""
    session = create_snowflake_session()
    try:
        session.write_pandas(
            df,
            table_name,
            auto_create_table=True,
            overwrite=True,
        )
    finally:
        session.close()


def load_from_snowflake(table_name: str) -> pd.DataFrame:
    """Lê a tabela do Snowflake e retorna como DataFrame pandas."""
    session = create_snowflake_session()
    try:
        exists = session.sql(
            f"SHOW TABLES LIKE '{table_name}' IN SCHEMA "
            f"{connection_parameters['database']}.{connection_parameters['schema']}"
        ).collect()
        if not exists:
            raise RuntimeError(
                f"A tabela '{table_name}' não existe em "
                f"{connection_parameters['database']}.{connection_parameters['schema']}. "
                "Clique primeiro em 'Carregar Dados no Snowflake'."
            )
        df = session.table(table_name).to_pandas()
    finally:
        session.close()
    return df

def main() -> None:
    st.sidebar.title("Controles")

    if st.sidebar.button("Carregar Dados no Snowflake"):
        try:
            with st.spinner("Baixando e filtrando os dados..."):
                df = load_filtered_data(DATA_URL)
            with st.spinner("Enviando dados para o Snowflake..."):
                upload_to_snowflake(df, TABLE_NAME)
            st.sidebar.success("Dados carregados no Snowflake com sucesso.")
        except Exception as e:
            st.sidebar.error(f"Erro ao carregar dados no Snowflake: {e}")

    if st.sidebar.button("Carregar Dashboard"):
        try:
            with st.spinner("Lendo dados do Snowflake..."):
                df = load_from_snowflake(TABLE_NAME)
                st.session_state["covid_data"] = df
            st.sidebar.success("Dashboard pronto para exibição.")
        except Exception as e:
            st.sidebar.error(f"Erro ao carregar dashboard: {e}")

    st.title("Dashboard COVID-19 - Our World in Data")
    st.markdown(
        "Este dashboard apresenta análises de casos, óbitos, vacinação e "
        "população para seis países selecionados."
    )
    st.markdown(f"Última atualização: {datetime.today().strftime('%Y-%m-%d')}")

    if "covid_data" not in st.session_state:
        st.info(
            "Use o botão 'Carregar Dados no Snowflake' (uma única vez) e depois "
            "'Carregar Dashboard' na barra lateral para exibir as visualizações."
        )
        return

    df = st.session_state["covid_data"].copy()
    df["date"] = pd.to_datetime(df["date"])

    st.subheader("Filtros")
    col_f1, col_f2 = st.columns(2)

    with col_f1:
        countries = sorted(df["location"].unique().tolist())
        selected_countries = st.multiselect(
            "Países selecionados",
            countries,
            default=countries,
        )

    with col_f2:
        min_date = df["date"].min().date()
        max_date = df["date"].max().date()
        selected_start, selected_end = st.slider(
            "Período",
            min_value=min_date,
            max_value=max_date,
            value=(min_date, max_date),
            format="DD/MM/YYYY",
        )

    if not selected_countries:
        st.warning("Selecione ao menos um país para visualizar o dashboard.")
        return

    df_filtered = df[
        (df["location"].isin(selected_countries))
        & (df["date"].dt.date >= selected_start)
        & (df["date"].dt.date <= selected_end)
    ].copy()

    if df_filtered.empty:
        st.warning("Nenhum dado encontrado para os filtros selecionados.")
        return

    total_cases = df_filtered["new_cases"].sum()
    total_deaths = df_filtered["new_deaths"].sum()
    avg_vax = (
        df_filtered.sort_values("date")
        .groupby("location")["people_vaccinated_per_hundred"]
        .last()
        .mean()
    )

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("Casos no período", f"{total_cases:,.0f}".replace(",", "."))
    kpi2.metric("Óbitos no período", f"{total_deaths:,.0f}".replace(",", "."))
    kpi3.metric(
        "Vacinação média (1 dose)",
        f"{avg_vax:.1f}%" if pd.notna(avg_vax) else "N/D",
    )
    kpi4.metric("Países analisados", len(selected_countries))

    st.markdown("---")

    st.subheader("1 - Evolução de casos novos ao longo do tempo")
    fig_new_cases = px.line(
        df_filtered.sort_values("date"),
        x="date",
        y="new_cases",
        color="location",
        title="Novos casos diários por país",
        labels={"new_cases": "Novos casos", "date": "Data", "location": "País"},
    )
    st.plotly_chart(fig_new_cases, use_container_width=True)

    st.subheader("2 - Comparação do total de óbitos")
    latest_deaths = (
        df_filtered.sort_values("date")
        .groupby("location", as_index=False)["total_deaths"]
        .last()
    )
    fig_deaths = px.bar(
        latest_deaths,
        x="location",
        y="total_deaths",
        color="location",
        title="Total de óbitos por país",
        labels={"total_deaths": "Óbitos totais", "location": "País"},
    )
    st.plotly_chart(fig_deaths, use_container_width=True)

    st.subheader("3 - Proporção de pessoas vacinadas (1 dose)")
    latest_vax = (
        df_filtered.sort_values("date")
        .groupby("location", as_index=False)["people_vaccinated_per_hundred"]
        .last()
    )
    latest_vax["people_vaccinated_per_hundred"] = latest_vax[
        "people_vaccinated_per_hundred"
    ].fillna(0)
    fig_vax = px.pie(
        latest_vax,
        names="location",
        values="people_vaccinated_per_hundred",
        title="Pessoas vacinadas (1 dose) por país (%)",
    )
    st.plotly_chart(fig_vax, use_container_width=True)

    st.subheader("4 - Relação entre população e total de casos")
    latest_population = (
        df_filtered.sort_values("date")
        .groupby("location", as_index=False)[["population", "total_cases"]]
        .last()
    )
    fig_scatter = px.scatter(
        latest_population,
        x="population",
        y="total_cases",
        color="location",
        size="population",
        hover_name="location",
        title="População versus total de casos por país",
        labels={"population": "População", "total_cases": "Total de casos"},
        size_max=60,
    )
    st.plotly_chart(fig_scatter, use_container_width=True)

    st.markdown("---")
    st.subheader("Dados de referência")
    st.dataframe(
        df_filtered.sort_values(["location", "date"]).reset_index(drop=True)
    )


if __name__ == "__main__":
    main()
