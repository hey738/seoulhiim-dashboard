import streamlit as st
import pandas as pd
import altair as alt
import gspread
import numpy as np
from datetime import datetime, timedelta

def authenticate():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return

    pw = st.sidebar.text_input("대시보드 비밀번호", type="password")

    if not pw:
        st.sidebar.warning("비밀번호를 입력해주세요.")
        st.stop()

    if pw == st.secrets["general"]["APP_PASSWORD"]:
        st.session_state.authenticated = True
        return

    st.sidebar.error("❌ 비밀번호가 틀렸습니다.")
    st.stop()

st.set_page_config(
    page_title="행정동·연령대별 장악도 분석", 
    layout="wide",
    page_icon="서울안녕내과.ico"
)

authenticate()

province_map = {
    '서울': '서울특별시', '인천': '인천광역시', '경기': '경기도', '광주': '광주광역시',
    '부산': '부산광역시', '대구': '대구광역시', '대전': '대전광역시', '울산': '울산광역시',
    '경남': '경상남도', '경북': '경상북도', '전남': '전라남도', '충북': '충청북도', '충남': '충청남도'
}

special_cities = {
    "수원시","성남시","안양시","부천시","안산시",
    "고양시","용인시","청주시","천안시",
    "전주시","포항시","창원시"
}

def build_mask(df, province, city, dong):
    mask = pd.Series(True, index=df.index)
    if province != "전체":
        mask &= df["시/도"] == province
    if city != "전체":
        mask &= df["시/군/구"] == city
    if dong != "전체":
        mask &= df["행정동"] == dong
    return mask

def split_address(addr: str):
    parts = addr.split()
    if parts[0]=="세종특별자치시" and len(parts)==2:
        return pd.Series({"시/도":parts[0],"시/군/구":"","행정동":parts[1]})
    elif len(parts)==4 and parts[1] in special_cities:
        return pd.Series({
            "시/도":parts[0],
            "시/군/구":f"{parts[1]} {parts[2]}",
            "행정동":parts[3]
        })
    elif len(parts)==3 and parts[1] not in special_cities:
        return pd.Series({
            "시/도":parts[0],
            "시/군/구":parts[1],
            "행정동":parts[2]
        })
    else:
        return pd.Series({"시/도":None,"시/군/구":None,"행정동":None})

@st.cache_data
def load_population():
    creds = st.secrets["gcp_service_account"]
    client = gspread.service_account_from_dict(creds)
    ws = client.open_by_key(st.secrets["google_sheets"]["sheet_id"]).worksheet("연령별인구현황")
    pop = pd.DataFrame(ws.get_all_records())

    split_df = pop["행정기관"].apply(split_address)
    split_df.columns = ["시/도","시/군/구","행정동"]

    df = pd.concat([pop, split_df], axis=1).dropna(subset=["시/도"])

    if "총 인구수" in df.columns:
        df = df.rename(columns={"총 인구수":"전체인구"})
    return df.set_index(["시/도","시/군/구","행정동"])

@st.cache_data
def load_patient_data():
    creds = st.secrets["gcp_service_account"]
    client = gspread.service_account_from_dict(creds)
    ws = client.open_by_key(st.secrets["google_sheets"]["sheet_id"]).worksheet("Sheet1")
    df = pd.DataFrame(ws.get_all_records())

    df["진료일자"] = pd.to_datetime(df["진료일자"], format="%Y%m%d")

    df = df.sort_values("진료일자").drop_duplicates("환자번호", keep="last")

    bins = list(range(0,101,10)) + [999]
    labels = ["9세이하"] + [f"{i}대" for i in range(10,100,10)] + ["100세이상"]
    df["연령대"] = pd.cut(df["나이"], bins=bins, labels=labels, right=False, include_lowest=True)
    acc = len(df[df["행정동"]!=""]) / len(df)

    df["시/도"] = df["시/도"].map(province_map).fillna(df["시/도"])

    df["행정기관"] = np.where(
        df["시/도"]=="세종특별자치시",
        df["시/도"]+" "+df["행정동"],
        df["시/도"]+" "+df["시/군/구"]+" "+df["행정동"]
    )
    return df, acc

pop_df = load_population()
patient_df, acc = load_patient_data()

# 드릴다운 처리 (위젯 렌더링 전에 session_state 설정)
if "_drilldown" in st.session_state:
    dd = st.session_state.pop("_drilldown")
    level, region = dd["level"], dd["region"]
    if level == "province":
        st.session_state["filter_province"] = region
        st.session_state.pop("filter_city", None)
        st.session_state.pop("filter_dong", None)
    elif level == "city":
        st.session_state["filter_city"] = region
        st.session_state.pop("filter_dong", None)
    elif level == "dong":
        st.session_state["filter_dong"] = region

# 사이드바 필터
with st.sidebar.expander("활성 환자 기간", True):
    months = st.slider("최근 몇 개월 활성", 1,24,12)
    cutoff = datetime.now() - timedelta(days=30*months)
    st.write(f"{cutoff.date()} 이후")

with st.sidebar.expander("지역 선택", True):
    provinces = ["전체"] + pop_df.index.get_level_values(0).unique().tolist()
    province = st.selectbox("시/도", provinces, key="filter_province")
    if province=="전체":
        cities=["전체"]
    else:
        cities = ["전체"] + pop_df.loc[province].index.get_level_values(0).unique().tolist()
    city = st.selectbox("시/군/구", cities, key="filter_city")
    if province=="전체" or city=="전체":
        dongs=["전체"]
    else:
        dongs = ["전체"] + pop_df.loc[(province,city)].index.get_level_values(0).unique().tolist()
    dong = st.selectbox("행정동", dongs, key="filter_dong")

# 활성 환자 데이터
active = patient_df[patient_df["진료일자"]>=cutoff].copy()

# --- pop_sel 슬라이스 & 컬럼 보강 ---
if dong!="전체":
    # single-row => DataFrame
    pop_sel = pop_df.loc[[(province,city,dong)]].reset_index()
elif city!="전체":
    pop_sel = pop_df.loc[(province,city)].reset_index()
elif province!="전체":
    pop_sel = pop_df.loc[province].reset_index()
else:
    pop_sel = pop_df.reset_index()

# ensure id_vars exist
pop_sel["시/도"]    = province if province!="전체" else pop_sel.get("시/도","")
pop_sel["시/군/구"] = city if city!="전체" else pop_sel.get("시/군/구","")
pop_sel["행정동"]   = dong if dong!="전체" else pop_sel.get("행정동","")
pop_sel["전체인구"] = pop_sel["전체인구"].fillna(0)

# 환자수 집계
mask_act = build_mask(active, province, city, dong)
grouped_pat = (
    active[mask_act]
    .groupby("연령대", observed=False)["환자번호"]
    .nunique()
    .reset_index(name="환자수")
)

# melt → merge → calc
age_cols = [c for c in pop_sel.columns if c in grouped_pat["연령대"].tolist()]
pop_melt = pop_sel.melt(
    id_vars=["시/도","시/군/구","행정동","전체인구"],
    value_vars=age_cols,
    var_name="연령대", value_name="인구수"
)

pop_melt["인구수"] = (
    pop_melt["인구수"].astype(str).str.replace(",","")
      .pipe(pd.to_numeric, errors="coerce")
)

grouped_pop = pop_melt.groupby('연령대')['인구수'].sum().reset_index(name='인구수')

merge_sel = (
    pd.merge(grouped_pop, grouped_pat, on="연령대", how="left")
      .fillna({"환자수":0})
)
merge_sel["장악도(%)"] = (
    merge_sel["환자수"]/merge_sel["인구수"]*100
)

# KPI 카드
total_pop       = int(pop_sel["전체인구"].sum())
total_patients  = patient_df[build_mask(patient_df,province,city,dong)]["환자번호"].nunique()
active_patients = active[mask_act]["환자번호"].nunique()
region_pen      = total_patients/total_pop*100 if total_pop else 0
period_pen      = active_patients/total_pop*100 if total_pop else 0

c1,c2,c3 = st.columns(3)
c1.metric("인구수",f"{total_pop:,}명", help="선택 지역의 주민등록 인구수")
c2.metric("환자수",f"{total_patients:,}명", help="선택 지역의 전체 기간 고유 환자수")
c3.metric("활성 환자수",f"{active_patients:,}명", help="선택 기간 내 내원한 고유 환자수")
c1.metric("데이터 완성도",f"{acc*100:.0f}%", help="전체 고유환자 중 행정동 매칭된 비율. 장악도 산출의 신뢰도 기준")
c2.metric("지역 장악도",f"{region_pen:.2f}%", help="전체 기간 누적 환자수 / 인구수")
c3.metric("기간내 장악도",f"{period_pen:.2f}%", help="선택 기간 활성 환자수 / 인구수")

st.markdown("---")

# 하위 지역별 장악도 랭킹
if dong == "전체":
    if province == "전체":
        sub_col = "시/도"
        sub_regions = pop_df.index.get_level_values(0).unique()
    elif city == "전체":
        sub_col = "시/군/구"
        sub_regions = pop_df.loc[province].index.get_level_values(0).unique()
    else:
        sub_col = "행정동"
        sub_regions = pop_df.loc[(province, city)].index.get_level_values(0).unique()

    ranking_data = []
    for region in sub_regions:
        if province == "전체":
            sub_pop = pop_df.loc[region]["전체인구"].sum()
            sub_patients = active[active["시/도"] == region]["환자번호"].nunique()
        else:
            sub_pop = pop_sel[pop_sel[sub_col] == region]["전체인구"].sum()
            sub_patients = active[active[sub_col] == region]["환자번호"].nunique()
        if sub_pop > 0:
            ranking_data.append({
                "지역": region,
                "인구수": sub_pop,
                "환자수": sub_patients,
                "장악도(%)": sub_patients / sub_pop * 100
            })

    if ranking_data:
        ranking_df = pd.DataFrame(ranking_data).sort_values("장악도(%)", ascending=False)
        if province == "전체":
            rank_title = "시/도별 장악도 랭킹"
        elif city == "전체":
            rank_title = f"{province} {sub_col}별 장악도 랭킹"
        else:
            rank_title = f"{province} {city} {sub_col}별 장악도 랭킹"
        st.subheader(rank_title)
        st.caption("💡 막대를 클릭하면 해당 지역으로 드릴다운됩니다")

        point_sel = alt.selection_point(name="region_click", fields=["지역"], on="click")

        rank_bar = (
            alt.Chart(ranking_df)
            .mark_bar(cursor="pointer")
            .encode(
                y=alt.Y("지역:N", sort=ranking_df["지역"].tolist(), title=None),
                x=alt.X("장악도(%):Q", title="장악도(%)"),
                color=alt.Color("장악도(%):Q", scale=alt.Scale(scheme="tealblues"), legend=None),
                tooltip=[
                    alt.Tooltip("지역:N", title="지역"),
                    alt.Tooltip("인구수:Q", title="인구수", format=","),
                    alt.Tooltip("환자수:Q", title="환자수", format=","),
                    alt.Tooltip("장악도(%):Q", title="장악도(%)", format=".2f")
                ]
            )
            .add_params(point_sel)
        )
        rank_chart = rank_bar.properties(
            height=max(len(ranking_df) * 25, 200)
        )
        event = st.altair_chart(rank_chart, width="stretch", on_select="rerun", key="rank_chart")

        # 클릭 이벤트 처리: 클릭한 지역으로 드릴다운
        sel = event.selection.get("region_click") if event.selection else None
        # sel 구조: list of dicts, e.g. [{"지역": "서울특별시"}]
        # 또는 dict with lists, e.g. {"지역": ["서울특별시"]}
        clicked = None
        if sel:
            if isinstance(sel, list) and len(sel) > 0 and "지역" in sel[0]:
                clicked = sel[0]["지역"]
            elif isinstance(sel, dict) and len(sel.get("지역", [])) > 0:
                clicked = sel["지역"][0]

        if clicked:
            if province == "전체":
                st.session_state["_drilldown"] = {"level": "province", "region": clicked}
            elif city == "전체":
                st.session_state["_drilldown"] = {"level": "city", "region": clicked}
            else:
                st.session_state["_drilldown"] = {"level": "dong", "region": clicked}
            st.rerun()

        st.markdown("---")

# 차트
custom_order = ["9세이하"]+[f"{i}대" for i in range(10,100,10)]+["100세이상"]
title = (
    f"{province} {city} {dong} 연령대 장악도" if dong!="전체" else
    f"{province} {city} 연령대 장악도" if city!="전체" else
    f"{province} 연령대 장악도" if province!="전체" else
    "전체 지역 연령대 장악도"
)
st.subheader(title)

bar = (
    alt.Chart(merge_sel)
      .mark_bar()
      .encode(
         x=alt.X("연령대:O",sort=custom_order,axis=alt.Axis(labelAngle=0)),
         y=alt.Y(
            "장악도(%):Q",
            axis=alt.Axis(format=".1f"),
            title="장악도(%)"
        ),
         tooltip=[
            alt.Tooltip("인구수:Q",title="인구수", format=","),
            alt.Tooltip("환자수:Q",title="환자수", format=","),
            alt.Tooltip("장악도(%):Q",title="장악도(%)",format=".1f")
         ]
      )
      .properties(height=400)
)

label_rate = (
    alt.Chart(merge_sel)
      .transform_calculate(
        display="""
          format(datum["장악도(%)"], ".1f") + "%"
        """
      )
      .mark_text(
        align='center',
        baseline='middle',
        dy=-50,
        fontWeight='bold',
        fontSize=16
      )
      .encode(
        x=alt.X('연령대:O', sort=custom_order),
        y=alt.Y('장악도(%):Q'),
        text=alt.Text('display:N')
      )
)

label_count = (
    alt.Chart(merge_sel)
      .transform_calculate(
        display="""
          format(datum["환자수"], ",") + '명 / ' +
          format(datum["인구수"], ",") + '명'
        """
      )
      .mark_text(
         dy=-30,                # 퍼센트 레이블에서 2px 아래
         fontWeight='bold',
         align='center',
         baseline='top',
          fontSize=14
      )
      .encode(
         x=alt.X('연령대:O', sort=custom_order),
         y=alt.Y('장악도(%):Q'),
         text=alt.Text('display:N')
      )
)

final = bar + label_rate + label_count
st.altair_chart(final, width='stretch')

df_t = merge_sel.set_index('연령대').T[custom_order].astype(str).copy()
df_t.loc['인구수']     = merge_sel.set_index('연령대')['인구수'].reindex(custom_order).astype(int).map("{:,}".format)
df_t.loc['환자수']     = merge_sel.set_index('연령대')['환자수'].reindex(custom_order).astype(int).map("{:,}".format)
df_t.loc['장악도(%)']  = merge_sel.set_index('연령대')['장악도(%)'].reindex(custom_order).map(lambda x: f"{x:.1f}%")
st.dataframe(df_t)
