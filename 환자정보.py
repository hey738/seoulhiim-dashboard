import streamlit as st
import pandas as pd
import altair as alt
import folium
import gspread
from streamlit_folium import folium_static
from folium.plugins import FastMarkerCluster

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

st.set_page_config(page_title="환자 대시보드", layout="wide")

authenticate()

# 1) 데이터 로드 (Google Sheets via API)
@st.cache_data
def load_data():
    creds_dict = st.secrets["gcp_service_account"]
    client = gspread.service_account_from_dict(creds_dict)
    sheet_id = st.secrets["google_sheets"]["sheet_id"]
    worksheet_name = st.secrets["google_sheets"]["worksheet_name"]
    sheet = client.open_by_key(sheet_id).worksheet(worksheet_name)
    records = sheet.get_all_records()
    return pd.DataFrame(records)

df = load_data()

# 2) 전처리
df['진료일자'] = pd.to_datetime(df['진료일자'], format='%Y%m%d')

def categorize_time(hms):
    if pd.isna(hms):
        time_str = '000000'
    else:
        try:
            val = int(hms)
            time_str = str(val).zfill(6)
        except:
            time_str = str(hms).zfill(6)
    hour = int(time_str[:2])
    return f"{hour:02d}"

df['진료시간대'] = df['진료시간'].apply(categorize_time)

bins = list(range(0, 101, 10)) + [999]
labels = ["9세이하"] + [f"{i}대" for i in range(10, 100, 10)] + ["100세이상"]
df['연령대'] = pd.cut(
    df['나이'],
    bins=bins,
    labels=labels,
    right=False,
    include_lowest=True
)

# 3) 사이드바 필터
st.sidebar.header("필터 설정")
start_date = st.sidebar.date_input("시작 진료일자", df['진료일자'].min())
end_date = st.sidebar.date_input("종료 진료일자", df['진료일자'].max())
age_band = st.sidebar.multiselect(
    "연령대",
    options=df['연령대'].cat.categories.tolist(),
    default=df['연령대'].cat.categories.tolist()
)
gender = st.sidebar.selectbox(
    "성별",
    options=["전체"] + df['성별'].dropna().unique().tolist()
)

filtered = df[
    (df['진료일자'] >= pd.to_datetime(start_date)) &
    (df['진료일자'] <= pd.to_datetime(end_date)) &
    (df['연령대'].isin(age_band))
]
if gender != "전체":
    filtered = filtered[filtered['성별'] == gender]

# 4) KPI 카드
patients_in_period = len(filtered.drop_duplicates("환자번호"))
counts_in_period = len(filtered)
new_count = len(filtered[filtered['초/재진'] == "신환"])
return_count = len(filtered[filtered['초/재진'] != "신환"])
new_ratio = new_count / counts_in_period if counts_in_period else 0
return_ratio = return_count / counts_in_period if counts_in_period else 0
avg_age = filtered['나이'].mean()

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("환자수", f"{patients_in_period:,}명")
col2.metric("진료 횟수", f"{counts_in_period:,}번")
col3.metric("신환 비율", f"{new_ratio:.1%}")
col4.metric("재방문 비율", f"{return_ratio:.1%}")
col5.metric("평균 연령", f"{avg_age:.1f}세")

st.markdown("---")

# 5) 일별 내원 추이 (토글 가능한 추세선)
st.subheader("일별 내원 추이")

# 일별 집계
daily = (
    filtered
    .groupby('진료일자')
    .size()
    .reset_index(name='환자수')
    .sort_values('진료일자')
)

# 이동평균 컬럼 추가
daily['MA6']  = daily['환자수'].rolling(window=6,  min_periods=1).mean()
daily['MA30'] = daily['환자수'].rolling(window=30, min_periods=1).mean()
daily['MA60'] = daily['환자수'].rolling(window=60, min_periods=1).mean()
daily['MA90'] = daily['환자수'].rolling(window=90, min_periods=1).mean()

# long form 변환
melted = daily.melt(
    id_vars='진료일자',
    value_vars=['환자수','MA6','MA30','MA60','MA90'],
    var_name='지표',
    value_name='값'
)
# 범례 클릭으로 토글할 셀렉션
legend_sel = alt.selection_multi(fields=['지표'], bind='legend')

# 차트
trend_chart = (
    alt.Chart(melted)
       .mark_line()
       .encode(
           x=alt.X('진료일자:T', title='진료일자'),
           y=alt.Y('값:Q',     title='진료횟수'),
           color=alt.Color(
               '지표:N',
               scale=alt.Scale(
                   domain=['환자수','MA6','MA30','MA60','MA90'],
                   range=['#FFDC3C','#4BA3C7','#00C49A','#FF8C42','#9B59B6']
               )
           ),
           opacity=alt.condition(legend_sel, alt.value(1), alt.value(0.1)),
           tooltip=[
               alt.Tooltip('진료일자:T', title='날짜'),
               alt.Tooltip('지표:N',      title='지표'),
               alt.Tooltip('값:Q',        title='내원수')
           ]
       )
       .add_params(legend_sel)
        .interactive()
       .properties(height=400)
)

daily_hover = (
    alt.Chart(melted)
       .mark_point(size=200, opacity=0)
       .transform_filter(alt.datum.지표=='환자수')
       .encode(
            x='진료일자:T', y='값:Q',
            tooltip=[
                alt.Tooltip('진료일자:T', title='날짜'),
                alt.Tooltip('값:Q',        title='내원수')
            ]
        )
)

trend_hover = (
    alt.Chart(melted)
       .mark_point(size=200, opacity=0)
       .transform_filter(alt.datum.지표!='환자수')
       .encode(
            x='진료일자:T', y='값:Q',
            tooltip=[
                alt.Tooltip('진료일자:T', title='날짜'),
                alt.Tooltip('지표:N',      title='지표'),
                alt.Tooltip('값:Q',        title='내원수')
            ]
        )
)

final_chart = (
    alt.layer(trend_chart, daily_hover, trend_hover)
       .resolve_scale(y='shared')
       .properties(
           width='container',
           autosize={'type':'fit-x','contains':'padding'}
       )
)
st.altair_chart(final_chart, use_container_width=True)

# 일별 집계
daily2 = (
    df
    .groupby('진료일자')
    .size()
    .reset_index(name='환자수')
    .sort_values('진료일자')
)

# 기준 기간 정의
start = pd.to_datetime(start_date)
end   = pd.to_datetime(end_date)

# 전년 동기 기간
ly_start = start - pd.DateOffset(years=1)
ly_end   = end   - pd.DateOffset(years=1)

# 기간별 필터링
curr = daily2[(daily2['진료일자'] >= start) & (daily2['진료일자'] <= end)].copy()
ly   = daily2[(daily2['진료일자'] >= ly_start) & (daily2['진료일자'] <= ly_end)].copy()

# 전년 데이터를 '금년 날짜'로 옮겨오기
ly['pseudo_date'] = ly['진료일자'] + pd.DateOffset(years=1)

# 비교용 컬럼 추가
curr['year_group'] = '조회 기간'
ly  ['year_group'] = '전년 동기'

# 날짜 컬럼 통일
curr['plot_date'] = curr['진료일자']
ly  ['plot_date'] = ly['pseudo_date']

# 합치기
comp = pd.concat([curr[['plot_date','환자수','year_group', '진료일자']],
                  ly  [['plot_date','환자수','year_group', '진료일자']]])

comp_area = (
    alt.Chart(comp)
      .mark_area(interpolate='monotone', opacity=0.4)
      .encode(
          x=alt.X('plot_date:T', title='진료일자'),
          y=alt.Y('환자수:Q', title='진료횟수', stack=None),
          color=alt.Color('year_group:N', title='기간',
                          scale=alt.Scale(domain=['조회 기간','전년 동기'],
                                          range=['#FFDC3C','#A0AEC0'])),
          tooltip=[
            alt.Tooltip('진료일자:T', title='날짜'),
            alt.Tooltip('환자수:Q',   title='내원수'),
            alt.Tooltip('year_group:N', title='기간')
          ]
      )
      .properties(height=400)
      .interactive()
)

# 필요하다면 투명 포인트로 hover 레이어 추가
comp_hover = (
    alt.Chart(comp)
      .mark_point(size=200, opacity=0)
      .encode(
          x='plot_date:T', y='환자수:Q',
          tooltip=[
            alt.Tooltip('진료일자:T', title='날짜'),
            alt.Tooltip('환자수:Q', title='내원수'),
            alt.Tooltip('year_group:N', title='기간')
          ]
      )
)

final_comp_chart = comp_area + comp_hover

# st.subheader("전년 동기 내원 추이 비교")
# #st.altair_chart(final_comp_chart, use_container_width=True)

# 1) 선택 기간 월별 집계
curr_monthly = (
    filtered
    .groupby(pd.Grouper(key='진료일자', freq='M'))
    .size()
    .reset_index(name='환자수')
)
# 2) 전년 동기 월별 집계
ly_filtered = df[
    (df['진료일자'] >= (pd.to_datetime(start_date) - pd.DateOffset(years=1))) &
    (df['진료일자'] <= (pd.to_datetime(end_date)   - pd.DateOffset(years=1)))
]
ly_monthly = (
    ly_filtered
    .groupby(pd.Grouper(key='진료일자', freq='M'))
    .size()
    .reset_index(name='환자수')
)
# 3) 날짜를 비교하기 쉽게 연동
ly_monthly['진료일자'] = ly_monthly['진료일자'] + pd.DateOffset(years=1)
# 4) growth_rate 계산
monthly = curr_monthly.merge(
    ly_monthly.rename(columns={'환자수':'ly_환자수'}),
    on='진료일자', how='left'
)
monthly['growth_rate'] = (monthly['환자수'] - monthly['ly_환자수']) / monthly['ly_환자수']

# NaN을 0으로 채우고 int로 변환
monthly['ly_환자수'] = monthly['ly_환자수'].fillna(0).astype(int)

monthly['count_label'] = (
    monthly['ly_환자수'].map(lambda x: f"{x:,}명") + "\\n-> " +
    monthly['환자수'].map(lambda x: f"{x:,}명")
)

# 5) 월간 성장률 차트
# 1) 막대 차트
month_bar = (
    alt.Chart(monthly)
      .transform_filter(alt.datum.growth_rate != None)
      .mark_bar()
      .encode(
          x=alt.X('yearmonth(진료일자):O', title='월'),
          y=alt.Y('growth_rate:Q', axis=alt.Axis(format='.1%')),
          tooltip=[
             alt.Tooltip('yearmonth(진료일자):T', title='월'),
             alt.Tooltip('growth_rate:Q',       title='성장률', format='.1%'),
             alt.Tooltip('환자수:Q',             title='이번 년 환자수'),
             alt.Tooltip('ly_환자수:Q',          title='전년 동기 환자수')
          ]
      )
      .properties(height=300, width={'step':60})
)

# 2) growth_rate 레이블 (막대 위쪽)
label_rate = (
    alt.Chart(monthly)
      .transform_filter(alt.datum.growth_rate != None)
      .mark_text(
          dy=-50,              # 막대 꼭대기 위로 약간 띄움
          align='center',
          baseline='bottom',
          fontWeight='bold',
          fontSize=16
      )
      .encode(
          x='yearmonth(진료일자):O',
          y='growth_rate:Q',
          text=alt.Text('growth_rate:Q', format='.1%')
      )
)

# 3) 환자수/전년환자수 레이블 (막대 바로 위나 아래)
label_count = (
    alt.Chart(monthly)
      .transform_filter(alt.datum.growth_rate != None)
      .mark_text(
          dy=-40,               # growth_rate 레이블 바로 아래
          align='center',
          baseline='top',
          fontWeight='bold',
          lineBreak='\\n',
          fontSize=14
      )
      .encode(
          x='yearmonth(진료일자):O',
          y='growth_rate:Q',
          text='count_label:N'
      )
)

# 막대 + 레이블 합성
final_month_bar = month_bar + label_rate + label_count

# st.subheader("월간 성장률")
# st.altair_chart(month_bar, use_container_width=True)

# 두 차트를 같은 행에 배치
col1, col2 = st.columns(2)

with col1:
    st.subheader("전년 동기 내원 추이 비교")
    st.altair_chart(final_comp_chart, use_container_width=True)

with col2:
    st.subheader("월간 성장률")
    st.altair_chart(final_month_bar, use_container_width=True)

# 7) 요일×시간대 히트맵
st.subheader("요일×시간대 내원 패턴")
filtered['요일'] = filtered['진료일자'].dt.day_name()
heat = filtered.groupby(['요일', '진료시간대']).size().reset_index(name='count')
heat_chart = alt.Chart(heat).mark_rect().encode(
    x=alt.X('진료시간대:O', title="시간대", axis=alt.Axis(labelAngle=0)),
    y=alt.Y('요일:O', sort=['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']),
    color=alt.Color('count:Q', scale=alt.Scale(scheme='blues'), title='내원수')
)
st.altair_chart(heat_chart, use_container_width=True)

# 7) 환자 지도 분포
st.subheader("환자 지도 분포")
m = folium.Map(location=[37.5665, 126.9780], zoom_start=7)
filtered['x'].replace("", pd.NA, inplace=True)
filtered['y'].replace("", pd.NA, inplace=True)
data = list(filtered.dropna(subset=['y','x'])[['y','x']].itertuples(index=False, name=None))
FastMarkerCluster(data).add_to(m)
folium_static(m, width=800, height=600)
