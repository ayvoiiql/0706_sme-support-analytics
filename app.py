import copy
import json

import branca.colormap as cm
import folium
import pandas as pd
import plotly.express as px
import streamlit as st
from pathlib import Path
from shapely.geometry import shape
from streamlit_folium import st_folium

DATA_DIR = Path(__file__).parent / "data"
LOCAL_CSV_PATH = DATA_DIR / "sme_support_local.csv"
CENTRAL_CSV_PATH = DATA_DIR / "sme_support_central.csv"
GEOJSON_PATH = DATA_DIR / "skorea_provinces_geo.json"

# geojson의 영문 지역명(name_eng) -> 데이터의 지자체명 매핑
NAME_ENG_TO_KR = {
    "Seoul": "서울", "Busan": "부산", "Daegu": "대구", "Incheon": "인천",
    "Gwangju": "광주", "Daejeon": "대전", "Ulsan": "울산", "Sejongsi": "세종",
    "Gyeonggi-do": "경기", "Gangwon-do": "강원", "Chungcheongbuk-do": "충북",
    "Chungcheongnam-do": "충남", "Jeollabuk-do": "전북", "Jeollanam-do": "전남",
    "Gyeongsangbuk-do": "경북", "Gyeongsangnam-do": "경남", "Jeju-do": "제주",
}

st.set_page_config(page_title="중소기업 지원사업 지역별 분석", layout="wide")


@st.cache_data
def load_data(local_path: Path, central_path: Path):
    local = pd.read_csv(local_path).rename(columns={"예산(백만원)": "예산"})
    central = pd.read_csv(central_path).rename(columns={"예산(백만원)": "예산"})
    return local, central


@st.cache_data
def load_geojson(path: Path):
    with open(path, encoding="utf-8") as f:
        geojson = json.load(f)

    centroids = {}
    for feature in geojson["features"]:
        region = NAME_ENG_TO_KR[feature["properties"]["name_eng"]]
        feature["properties"]["region"] = region
        point = shape(feature["geometry"]).representative_point()
        centroids[region] = (point.y, point.x)

    return geojson, centroids


def build_region_map(summary: pd.DataFrame, centroids: dict):
    counts = summary.set_index("지자체명")[["사업수", "총예산"]].to_dict("index")
    geojson = copy.deepcopy(base_geojson)
    for feature in geojson["features"]:
        region = feature["properties"]["region"]
        info = counts.get(region, {"사업수": 0, "총예산": 0.0})
        feature["properties"]["사업수"] = int(info["사업수"])
        feature["properties"]["총예산"] = round(float(info["총예산"]), 1)

    max_count = max((f["properties"]["사업수"] for f in geojson["features"]), default=0)
    colormap = cm.LinearColormap(
        colors=["#fff5eb", "#fd8d3c", "#a63603"],
        vmin=0,
        vmax=max(max_count, 1),
        caption="지원사업 수",
    )

    m = folium.Map(location=[36.4, 127.9], zoom_start=7, tiles="cartodbpositron")

    folium.GeoJson(
        geojson,
        name="지원사업 수",
        style_function=lambda feat: {
            "fillColor": colormap(feat["properties"]["사업수"]),
            "color": "#555555",
            "weight": 1,
            "fillOpacity": 0.75,
        },
        highlight_function=lambda feat: {"weight": 3, "color": "#000000", "fillOpacity": 0.9},
        tooltip=folium.GeoJsonTooltip(
            fields=["region", "사업수", "총예산"],
            aliases=["지자체", "지원사업 수", "총예산(백만원)"],
        ),
    ).add_to(m)

    for region, (lat, lon) in centroids.items():
        count = counts.get(region, {"사업수": 0})["사업수"]
        folium.map.Marker(
            location=[lat, lon],
            icon=folium.DivIcon(
                icon_size=(40, 20),
                icon_anchor=(20, 10),
                html=(
                    '<div style="pointer-events:none; text-align:center; font-size:12px; '
                    'font-weight:700; color:#1a1a1a; text-shadow:1px 1px 2px #fff, '
                    '-1px -1px 2px #fff, 1px -1px 2px #fff, -1px 1px 2px #fff;">'
                    f"{count}</div>"
                ),
            ),
        ).add_to(m)

    colormap.add_to(m)
    return m


local_df, central_df = load_data(LOCAL_CSV_PATH, CENTRAL_CSV_PATH)
base_geojson, region_centroids = load_geojson(GEOJSON_PATH)

st.title("지역별 중소기업 지원사업 분석")
st.caption("중소벤처기업부 · 중소기업지원사업 현황 (2025-12-31 기준, 단위: 백만원)")

# ---------------- 사이드바 필터 ----------------
st.sidebar.header("필터")

all_regions = sorted(local_df["지자체명"].unique())
selected_regions = st.sidebar.multiselect("지자체 선택", all_regions, default=all_regions)

keyword = st.sidebar.text_input("사업명 검색")

min_budget, max_budget = float(local_df["예산"].min()), float(local_df["예산"].max())
budget_range = st.sidebar.slider(
    "예산 범위 (백만원)",
    min_value=min_budget,
    max_value=max_budget,
    value=(min_budget, max_budget),
)

filtered = local_df[
    local_df["지자체명"].isin(selected_regions)
    & local_df["예산"].between(budget_range[0], budget_range[1])
]
if keyword:
    filtered = filtered[filtered["세부사업명"].str.contains(keyword, case=False, na=False)]

if filtered.empty:
    st.warning("선택한 조건에 해당하는 데이터가 없습니다.")
    st.stop()

# ---------------- 요약 지표 ----------------
col1, col2, col3, col4 = st.columns(4)
col1.metric("지원사업 수", f"{len(filtered):,}건")
col2.metric("총 예산", f"{filtered['예산'].sum():,.0f}백만원")
col3.metric("참여 지자체 수", f"{filtered['지자체명'].nunique()}곳")
col4.metric("사업당 평균 예산", f"{filtered['예산'].mean():,.1f}백만원")

st.divider()

# ---------------- 지역별 집계 ----------------
region_summary = (
    filtered.groupby("지자체명")
    .agg(사업수=("세부사업명", "count"), 총예산=("예산", "sum"), 평균예산=("예산", "mean"))
    .reset_index()
    .sort_values("총예산", ascending=False)
)

tab_map, tab1, tab2, tab3 = st.tabs(["지도", "지역별 예산/사업수", "예산 비중", "사업 목록"])

with tab_map:
    st.subheader("지역별 지원사업 수 지도")
    st.caption("지도 위 숫자는 현재 필터가 적용된 지원사업 수입니다. 지역을 클릭하면 아래에 해당 지역의 지원사업 목록이 표시됩니다.")

    region_map = build_region_map(region_summary, region_centroids)
    map_state = st_folium(
        region_map,
        width=900,
        height=600,
        returned_objects=["last_active_drawing"],
        key="region_map",
    )

    if map_state and map_state.get("last_active_drawing"):
        st.session_state["map_selected_region"] = map_state["last_active_drawing"]["properties"].get("region")

    selected_region = st.session_state.get("map_selected_region")

    if selected_region and selected_region in filtered["지자체명"].values:
        region_rows = filtered[filtered["지자체명"] == selected_region].sort_values("예산", ascending=False)
        st.markdown(f"#### {selected_region} 지원사업 목록 ({len(region_rows)}건)")
        m1, m2 = st.columns(2)
        m1.metric("지원사업 수", f"{len(region_rows):,}건")
        m2.metric("총 예산", f"{region_rows['예산'].sum():,.0f}백만원")
        st.dataframe(
            region_rows[["세부사업명", "예산"]].reset_index(drop=True),
            width='stretch',
        )
    elif selected_region:
        st.info(f"현재 필터 조건에서는 '{selected_region}' 지역의 데이터가 없습니다.")
    else:
        st.info("지도에서 지역을 클릭하면 해당 지역의 지원사업 목록이 표시됩니다.")

with tab1:
    c1, c2 = st.columns(2)
    with c1:
        fig_budget = px.bar(
            region_summary,
            x="지자체명",
            y="총예산",
            title="지역별 총 예산",
            labels={"총예산": "총 예산(백만원)", "지자체명": "지자체"},
            color="총예산",
            color_continuous_scale="Blues",
        )
        fig_budget.update_layout(xaxis={"categoryorder": "total descending"})
        st.plotly_chart(fig_budget, width='stretch')

    with c2:
        fig_count = px.bar(
            region_summary.sort_values("사업수", ascending=False),
            x="지자체명",
            y="사업수",
            title="지역별 지원사업 수",
            labels={"사업수": "사업 수", "지자체명": "지자체"},
            color="사업수",
            color_continuous_scale="Oranges",
        )
        fig_count.update_layout(xaxis={"categoryorder": "total descending"})
        st.plotly_chart(fig_count, width='stretch')

    fig_avg = px.bar(
        region_summary.sort_values("평균예산", ascending=False),
        x="지자체명",
        y="평균예산",
        title="지역별 사업당 평균 예산",
        labels={"평균예산": "평균 예산(백만원)", "지자체명": "지자체"},
    )
    fig_avg.update_layout(xaxis={"categoryorder": "total descending"})
    st.plotly_chart(fig_avg, width='stretch')

with tab2:
    fig_pie = px.pie(
        region_summary,
        names="지자체명",
        values="총예산",
        title="지역별 예산 비중",
        hole=0.4,
    )
    st.plotly_chart(fig_pie, width='stretch')

    fig_tree = px.treemap(
        filtered,
        path=["지자체명", "세부사업명"],
        values="예산",
        title="지자체 · 세부사업별 예산 트리맵",
    )
    st.plotly_chart(fig_tree, width='stretch')

with tab3:
    st.subheader("예산 상위 사업 TOP 10")
    top10 = filtered.sort_values("예산", ascending=False).head(10)
    st.dataframe(
        top10[["지자체명", "세부사업명", "예산"]].reset_index(drop=True),
        width='stretch',
    )

    st.subheader("지역별 집계 데이터")
    st.dataframe(region_summary.reset_index(drop=True), width='stretch')

    st.subheader("전체 사업 목록 (필터 적용)")
    st.dataframe(
        filtered[["지자체명", "세부사업명", "예산"]].reset_index(drop=True),
        width='stretch',
    )

    csv = filtered.to_csv(index=False).encode("utf-8-sig")
    st.download_button("필터링된 데이터 CSV 다운로드", data=csv, file_name="지역별_지원사업_필터결과.csv")

with st.expander("참고: 중앙부처 지원사업 현황 (지역명이 포함된 사업)"):
    region_keyword_pattern = "|".join(all_regions)
    central_regional = central_df[
        central_df["세부사업명"].str.contains(region_keyword_pattern, na=False)
    ]
    st.caption("세부사업명에 지자체명이 포함된 중앙부처 사업입니다 (예: 지역특화산업육성(세종)).")
    st.dataframe(
        central_regional[["소관명", "세부사업명", "예산"]].reset_index(drop=True),
        width='stretch',
    )
