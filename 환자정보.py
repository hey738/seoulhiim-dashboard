import streamlit as st
import pandas as pd
import altair as alt
import folium
import gspread
from streamlit_folium import st_folium
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

st.set_page_config(
    page_title="환자 대시보드",
    layout="wide",
    page_icon="서울안녕내과.ico"
)

authenticate()

st.markdown("""
<style>
    div[data-testid="stMetric"] .metric-container { gap: 0; }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] { font-size: 1.8rem; }
</style>
""", unsafe_allow_html=True)

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
new_patients = filtered[filtered['초/재진'] == "신환"]['환자번호'].nunique()
return_patients = patients_in_period - new_patients
new_ratio = new_patients / patients_in_period if patients_in_period else 0
return_ratio = return_patients / patients_in_period if patients_in_period else 0
avg_age = filtered['나이'].mean()

# 기준 기간 정의
start = pd.to_datetime(start_date)
end   = pd.to_datetime(end_date)

# 전년 동기 기간
ly_start = start - pd.DateOffset(years=1)
ly_end   = end   - pd.DateOffset(years=1)

# 전년 동기에도 연령대/성별 필터 적용
ly_filtered = df[
    (df['진료일자'] >= ly_start) &
    (df['진료일자'] <= ly_end) &
    (df['연령대'].isin(age_band))
]
if gender != "전체":
    ly_filtered = ly_filtered[ly_filtered['성별'] == gender]

# 전년 대비 성장률
ly_total_visits = ly_filtered.shape[0]
visit_growth = ((counts_in_period - ly_total_visits) / ly_total_visits * 100) if ly_total_visits > 0 else 0
ly_total_patients = ly_filtered['환자번호'].nunique()
patient_growth = ((patients_in_period - ly_total_patients) / ly_total_patients * 100) if ly_total_patients > 0 else 0
ly_new_patients = ly_filtered[ly_filtered['초/재진'] == "신환"]['환자번호'].nunique()
ly_new_ratio = ly_new_patients / ly_total_patients if ly_total_patients else 0
new_ratio_delta = (new_ratio - ly_new_ratio) * 100  # %p 변화

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("진료 횟수", f"{counts_in_period:,}건", f"{visit_growth:+.1f}%")
col2.metric("환자수", f"{patients_in_period:,}명", f"{patient_growth:+.1f}%")
col3.metric("신환 비율", f"{new_ratio:.1%}", f"{new_ratio_delta:+.1f}%p")
visits_per_patient = counts_in_period / patients_in_period if patients_in_period else 0
col4.metric("인당 진료횟수", f"{visits_per_patient:.1f}건")
col5.metric("평균 연령", f"{avg_age:.1f}세")

st.markdown("---")

# 일별 집계 (filtered 기준)
curr = (
    filtered.groupby('진료일자').size()
    .reset_index(name='진료횟수').sort_values('진료일자')
)
ly = (
    ly_filtered.groupby('진료일자').size()
    .reset_index(name='진료횟수').sort_values('진료일자')
)

# 전년 데이터를 '금년 날짜'로 옮겨오기
ly['pseudo_date'] = ly['진료일자'] + pd.DateOffset(years=1)

# 비교용 컬럼 추가
curr['year_group'] = '조회 기간'
ly  ['year_group'] = '전년 동기'

# 날짜 컬럼 통일
curr['plot_date'] = curr['진료일자']
ly  ['plot_date'] = ly['pseudo_date']

# 합치기
comp = pd.concat([curr[['plot_date','진료횟수','year_group', '진료일자']],
                  ly  [['plot_date','진료횟수','year_group', '진료일자']]])

comp_area = (
    alt.Chart(comp)
      .mark_area(interpolate='monotone', opacity=0.4)
      .encode(
          x=alt.X('plot_date:T', title='진료일자', axis=alt.Axis(
              format='%Y-%m',
              labelExpr=(
                  "date(datum.value) === 1 && month(datum.value) === 0 "
                  "? timeFormat(datum.value, '%Y') "
                  ": date(datum.value) === 1 "
                  "? timeFormat(datum.value, '%m') "
                  ": timeFormat(datum.value, '%m-%d')"
              )
          )),
          y=alt.Y('진료횟수:Q', title='진료횟수', stack=None),
          color=alt.Color('year_group:N', title='기간',
                          scale=alt.Scale(domain=['조회 기간','전년 동기'],
                                          range=['#FFDC3C','#A0AEC0'])),
          tooltip=[
            alt.Tooltip('진료일자:T', title='날짜', format='%Y-%m-%d'),
            alt.Tooltip('진료횟수:Q',   title='진료횟수'),
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
          x='plot_date:T', y='진료횟수:Q',
          tooltip=[
            alt.Tooltip('진료일자:T', title='날짜', format='%Y-%m-%d'),
            alt.Tooltip('진료횟수:Q', title='진료횟수'),
            alt.Tooltip('year_group:N', title='기간')
          ]
      )
)

final_comp_chart = comp_area + comp_hover

# 1) 선택 기간 월별 집계
curr_monthly = (
    filtered
    .groupby(pd.Grouper(key='진료일자', freq='ME'))
    .size()
    .reset_index(name='진료횟수')
)
# 2) 전년 동기 월별 집계 (위에서 만든 ly_filtered 재사용)
ly_monthly = (
    ly_filtered
    .groupby(pd.Grouper(key='진료일자', freq='ME'))
    .size()
    .reset_index(name='진료횟수')
)
# 3) 날짜를 비교하기 쉽게 연동
ly_monthly['진료일자'] = ly_monthly['진료일자'] + pd.DateOffset(years=1)
# 4) 성장률 계산
monthly = curr_monthly.merge(
    ly_monthly.rename(columns={'진료횟수':'ly_진료횟수'}),
    on='진료일자', how='left'
)
monthly['성장률'] = (monthly['진료횟수'] - monthly['ly_진료횟수']) / monthly['ly_진료횟수']

# NaN을 0으로 채우고 int로 변환
monthly['ly_진료횟수'] = monthly['ly_진료횟수'].fillna(0).astype(int)

monthly['count_label'] = (
    monthly['ly_진료횟수'].map(lambda x: f"{x:,}건") + "\\n-> " +
    monthly['진료횟수'].map(lambda x: f"{x:,}건")
)

# 5) 월간 성장률 차트
# 1) 막대 차트
month_bar = (
    alt.Chart(monthly)
      .transform_filter(alt.datum.성장률 != None)
      .mark_bar()
      .encode(
          x=alt.X('yearmonth(진료일자):O', title='진료일자', axis=alt.Axis(labelExpr="timeFormat(datum.value, '%Y-%m')", labelAngle=-45, labelOverlap=False)),
          y=alt.Y('성장률:Q', axis=alt.Axis(format='.1%', labelExpr="datum.value >= 0 ? format(datum.value, '.0%') + ' 증가' : format(-datum.value, '.0%') + ' 감소'")),
          tooltip=[
             alt.Tooltip('yearmonth(진료일자):T', title='월', format='%Y-%m'),
             alt.Tooltip('성장률:Q',       title='성장률', format='.1%'),
             alt.Tooltip('진료횟수:Q',             title='이번 년 진료횟수'),
             alt.Tooltip('ly_진료횟수:Q',          title='전년 동기 진료횟수')
          ]
      )
      .properties(height=300, width={'step':60})
)

# 2) 성장률 레이블 (막대 위쪽)
label_rate = (
    alt.Chart(monthly)
      .transform_filter(alt.datum.성장률 != None)
      .mark_text(
          dy=-50,              # 막대 꼭대기 위로 약간 띄움
          align='center',
          baseline='bottom',
          fontWeight='bold',
          fontSize=16
      )
      .encode(
          x='yearmonth(진료일자):O',
          y='성장률:Q',
          text=alt.Text('성장률:Q', format='.1%')
      )
)

# 3) 환자수/전년환자수 레이블 (막대 바로 위나 아래)
label_count = (
    alt.Chart(monthly)
      .transform_filter(alt.datum.성장률 != None)
      .mark_text(
          dy=-40,               # 성장률 레이블 바로 아래
          align='center',
          baseline='top',
          fontWeight='bold',
          lineBreak='\\n',
          fontSize=14
      )
      .encode(
          x='yearmonth(진료일자):O',
          y='성장률:Q',
          text='count_label:N'
      )
)

# 막대 + 레이블 합성
final_month_bar = month_bar + label_rate + label_count

# 두 차트를 같은 행에 배치
col1, col2 = st.columns(2)

with col1:
    st.subheader("전년 동기 내원 추이 비교")
    st.altair_chart(final_comp_chart, width='stretch')

with col2:
    st.subheader("월간 성장률")
    st.altair_chart(final_month_bar, width='stretch')

# 5) 내원 추이 (토글 가능한 추세선)
st.subheader("내원 추이")
agg_basis = st.radio("집계 기준", ["일별", "주별", "월별", "년별"], horizontal=True)

# 집계 기준에 따른 groupby 분기
if agg_basis == "일별":
    daily = (
        filtered
        .groupby('진료일자')
        .size()
        .reset_index(name='진료횟수')
        .sort_values('진료일자')
    )
else:
    freq_map = {"주별": "W", "월별": "ME", "년별": "YE"}
    daily = (
        filtered
        .groupby(pd.Grouper(key='진료일자', freq=freq_map[agg_basis]))
        .size()
        .reset_index(name='진료횟수')
        .sort_values('진료일자')
    )

# 이동평균 컬럼 추가
daily['MA6']  = daily['진료횟수'].rolling(window=6,  min_periods=1).mean()
daily['MA30'] = daily['진료횟수'].rolling(window=30, min_periods=1).mean()
daily['MA60'] = daily['진료횟수'].rolling(window=60, min_periods=1).mean()
daily['MA90'] = daily['진료횟수'].rolling(window=90, min_periods=1).mean()

# long form 변환
melted = daily.melt(
    id_vars='진료일자',
    value_vars=['진료횟수','MA6','MA30','MA60','MA90'],
    var_name='지표',
    value_name='값'
)
# 범례 클릭으로 토글할 셀렉션
legend_sel = alt.selection_point(fields=['지표'], bind='legend', value=[{'지표': 'MA30'}])

# x축 공통 설정
x_axis = alt.X('진료일자:T', title='날짜', axis=alt.Axis(
    format='%Y-%m',
    labelExpr=(
        "date(datum.value) === 1 && month(datum.value) === 0 "
        "? timeFormat(datum.value, '%Y') "
        ": date(datum.value) === 1 "
        "? timeFormat(datum.value, '%m') "
        ": timeFormat(datum.value, '%m-%d')"
    )
))

# 진료횟수: 얇은 area (배경, 항상 표시)
area_chart = (
    alt.Chart(melted)
       .transform_filter(alt.datum.지표 == '진료횟수')
       .mark_area(opacity=0.15, color='#FFDC3C', line={'strokeWidth': 1, 'color': '#D4A800'})
       .encode(
           x=x_axis,
           y=alt.Y('값:Q', title='진료횟수'),
           tooltip=[
               alt.Tooltip('진료일자:T', title='날짜', format='%Y-%m-%d'),
               alt.Tooltip('값:Q',        title='진료횟수')
           ]
       )
)

# MA 라인: 범례 토글
ma_chart = (
    alt.Chart(melted)
       .transform_filter(alt.datum.지표 != '진료횟수')
       .mark_line(strokeWidth=2)
       .encode(
           x=x_axis,
           y='값:Q',
           color=alt.Color(
               '지표:N',
               scale=alt.Scale(
                   domain=['MA6','MA30','MA60','MA90'],
                   range=['#4BA3C7','#00C49A','#FF8C42','#9B59B6']
               )
           ),
           opacity=alt.condition(legend_sel, alt.value(1), alt.value(0.1)),
           tooltip=[
               alt.Tooltip('진료일자:T', title='날짜', format='%Y-%m-%d'),
               alt.Tooltip('지표:N',      title='지표'),
               alt.Tooltip('값:Q',        title='진료횟수')
           ]
       )
       .add_params(legend_sel)
       .interactive()
       .properties(height=400)
)

daily_hover = (
    alt.Chart(melted)
       .mark_point(size=200, opacity=0)
       .transform_filter(alt.datum.지표=='진료횟수')
       .encode(
            x='진료일자:T', y='값:Q',
            tooltip=[
                alt.Tooltip('진료일자:T', title='날짜', format='%Y-%m-%d'),
                alt.Tooltip('값:Q',        title='진료횟수')
            ]
        )
)

trend_hover = (
    alt.Chart(melted)
       .mark_point(size=200, opacity=0)
       .transform_filter(alt.datum.지표!='진료횟수')
       .encode(
            x='진료일자:T', y='값:Q',
            tooltip=[
                alt.Tooltip('진료일자:T', title='날짜', format='%Y-%m-%d'),
                alt.Tooltip('지표:N',      title='지표'),
                alt.Tooltip('값:Q',        title='진료횟수')
            ]
        )
)

final_chart = (
    alt.layer(area_chart, ma_chart, daily_hover, trend_hover)
       .resolve_scale(y='shared')
       .properties(
           width='container',
           autosize={'type':'fit-x','contains':'padding'}
       )
)
st.altair_chart(final_chart, width='stretch')

# 7) 요일×시간대 히트맵
st.subheader("요일×시간대 내원 패턴")
day_kr = {'Monday':'월요일','Tuesday':'화요일','Wednesday':'수요일','Thursday':'목요일','Friday':'금요일','Saturday':'토요일','Sunday':'일요일'}
filtered['요일'] = filtered['진료일자'].dt.day_name().map(day_kr)
heat = filtered.groupby(['요일', '진료시간대']).size().reset_index(name='count')
heat_chart = alt.Chart(heat).mark_rect().encode(
    x=alt.X('진료시간대:O', title="시간대", axis=alt.Axis(labelAngle=0)),
    y=alt.Y('요일:O', sort=['월요일','화요일','수요일','목요일','금요일','토요일','일요일']),
    color=alt.Color('count:Q', scale=alt.Scale(scheme='blues'), title='내원수')
)
st.altair_chart(heat_chart, width='stretch')

# 7) 환자 지도 분포
st.subheader("환자 지도 분포")
m = folium.Map(location=[37.5665, 126.9780], zoom_start=7)
folium.plugins.Fullscreen().add_to(m)
unique_patients = filtered.drop_duplicates(subset='환자번호').copy()
unique_patients['x'] = unique_patients['x'].replace("", pd.NA)
unique_patients['y'] = unique_patients['y'].replace("", pd.NA)
data = list(unique_patients.dropna(subset=['y','x'])[['y','x']].itertuples(index=False, name=None))
FastMarkerCluster(data).add_to(m)
st_folium(m, width=800, height=600, returned_objects=[])

