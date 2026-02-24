import streamlit as st
import pandas as pd
import altair as alt
import gspread
from datetime import datetime, timedelta
import numpy as np

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
    page_title="마케팅 성과 분석",
    layout="wide",
    page_icon="서울안녕내과.ico"
)
authenticate()

st.title("마케팅 성과 분석")

# 데이터 로드
@st.cache_data
def load_data():
    creds_dict = st.secrets["gcp_service_account"]
    client = gspread.service_account_from_dict(creds_dict)
    sheet_id = st.secrets["google_sheets"]["sheet_id"]
    worksheet_name = st.secrets["google_sheets"]["worksheet_name"]
    sheet = client.open_by_key(sheet_id).worksheet(worksheet_name)
    records = sheet.get_all_records()
    return pd.DataFrame(records)

@st.cache_data
def load_population_data():
    creds_dict = st.secrets["gcp_service_account"]
    client = gspread.service_account_from_dict(creds_dict)
    sheet_id = st.secrets["google_sheets"]["sheet_id"]
    worksheet_name = "연령별인구현황"
    sheet = client.open_by_key(sheet_id).worksheet(worksheet_name)
    records = sheet.get_all_records()
    return pd.DataFrame(records)

df = load_data()
pop_df = load_population_data()

# 데이터 전처리
df['진료일자'] = pd.to_datetime(df['진료일자'], format='%Y%m%d')

# 나이대 카테고리
bins = list(range(0, 101, 10)) + [999]
labels = ["9세이하"] + [f"{i}대" for i in range(10, 100, 10)] + ["100세이상"]
df['연령대'] = pd.cut(df['나이'], bins=bins, labels=labels, right=False, include_lowest=True)

# 사이드바 - 캠페인 설정
st.sidebar.header("🎯 캠페인 설정")

# 캠페인 기간 설정
st.sidebar.subheader("캠페인 기간")
campaign_start = st.sidebar.date_input(
    "시작일",
    value=datetime.now() - timedelta(days=30),
    max_value=datetime.now()
)
campaign_end = st.sidebar.date_input(
    "종료일",
    value=datetime.now() - timedelta(days=1),
    max_value=datetime.now()
)

if campaign_start >= campaign_end:
    st.sidebar.error("종료일은 시작일보다 이후여야 합니다.")
    st.stop()

campaign_days = (campaign_end - campaign_start).days + 1

# 비교 기간 설정
st.sidebar.subheader("비교 기간")
comparison_option = st.sidebar.radio(
    "비교 기준",
    ["이전 동일 기간", "전년 동기", "사용자 지정"]
)

if comparison_option == "이전 동일 기간":
    before_end = campaign_start - timedelta(days=1)
    before_start = before_end - timedelta(days=campaign_days-1)
elif comparison_option == "전년 동기":
    before_start = campaign_start - timedelta(days=365)
    before_end = campaign_end - timedelta(days=365)
else:
    before_start = st.sidebar.date_input("비교 시작일")
    before_end = st.sidebar.date_input("비교 종료일")

# 타겟 지역 선택
st.sidebar.subheader("타겟 지역")
all_gu = sorted(df.loc[df['시/군/구'].str.strip().astype(bool), '시/군/구'].unique().tolist())
selected_gu = st.sidebar.selectbox("시/군/구", ["전체"] + all_gu)

if selected_gu == "전체":
    dong_options = sorted(df.loc[df['행정동'].str.strip().astype(bool), '행정동'].unique().tolist())
else:
    dong_options = sorted(df.loc[(df['시/군/구'] == selected_gu) & df['행정동'].str.strip().astype(bool), '행정동'].unique().tolist())

target_regions = st.sidebar.multiselect(
    "행정동 선택",
    options=dong_options,
    default=[d for d in ['월곶동', '배곧1동', '배곧2동'] if d in dong_options]
)

# 데이터 필터링
campaign_data = df[
    (df['진료일자'] >= pd.to_datetime(campaign_start)) &
    (df['진료일자'] <= pd.to_datetime(campaign_end))
]

before_data = df[
    (df['진료일자'] >= pd.to_datetime(before_start)) &
    (df['진료일자'] <= pd.to_datetime(before_end))
]

# 캠페인 후 30일 데이터
after_start = campaign_end + timedelta(days=1)
after_end = campaign_end + timedelta(days=30)
after_data = df[
    (df['진료일자'] >= pd.to_datetime(after_start)) &
    (df['진료일자'] <= pd.to_datetime(after_end))
]

# ── 기간 정보 표시 ──
col1, col2, col3 = st.columns(3)
with col1:
    st.info(f"**캠페인 기간**: {campaign_start} ~ {campaign_end} ({campaign_days}일)")
with col2:
    st.info(f"**비교 기간**: {before_start} ~ {before_end}")
with col3:
    if len(target_regions) > 0:
        st.info(f"**타겟 지역**: {', '.join(target_regions[:3])}{'...' if len(target_regions) > 3 else ''}")
    else:
        st.info("**타겟 지역**: 전체")

# 데이터 완성도
campaign_total = len(campaign_data)
campaign_missing = campaign_data['행정동'].isna() | ~campaign_data['행정동'].str.strip().astype(bool)
missing_count = campaign_missing.sum()
completeness = (1 - missing_count / campaign_total) * 100 if campaign_total > 0 else 0
if missing_count > 0:
    st.caption(f"📋 지역 데이터 완성도: {completeness:.1f}% (행정동 미입력 {missing_count:,}건 / 전체 {campaign_total:,}건 — 미입력 건은 지역별 분석에서 제외)")

# ── 캠페인 성과 지표 (KPI) ──
st.subheader("캠페인 성과 지표")

# 타겟 지역 필터링
if target_regions:
    campaign_target = campaign_data[campaign_data['행정동'].isin(target_regions)]
    before_target = before_data[before_data['행정동'].isin(target_regions)]
    campaign_non_target = campaign_data[~campaign_data['행정동'].isin(target_regions)]
    before_non_target = before_data[~before_data['행정동'].isin(target_regions)]
else:
    campaign_target = campaign_data
    before_target = before_data
    campaign_non_target = pd.DataFrame()
    before_non_target = pd.DataFrame()

# KPI 계산
new_patients_campaign = campaign_target[campaign_target['초/재진'] == '신환']['환자번호'].nunique()
new_patients_before = before_target[before_target['초/재진'] == '신환']['환자번호'].nunique()
new_patient_growth = ((new_patients_campaign - new_patients_before) / new_patients_before * 100) if new_patients_before > 0 else 0

unique_patients_campaign = campaign_target['환자번호'].nunique()
unique_patients_before = before_target['환자번호'].nunique()
patient_growth = ((unique_patients_campaign - unique_patients_before) / unique_patients_before * 100) if unique_patients_before > 0 else 0

new_ratio_campaign = (new_patients_campaign / unique_patients_campaign * 100) if unique_patients_campaign > 0 else 0
new_ratio_before = (new_patients_before / unique_patients_before * 100) if unique_patients_before > 0 else 0
new_ratio_change = new_ratio_campaign - new_ratio_before

total_visits_campaign = len(campaign_target)
total_visits_before = len(before_target)
visits_per_patient_campaign = total_visits_campaign / unique_patients_campaign if unique_patients_campaign > 0 else 0
visits_per_patient_before = total_visits_before / unique_patients_before if unique_patients_before > 0 else 0
visits_per_patient_change = visits_per_patient_campaign - visits_per_patient_before

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric(
        "신환 수",
        f"{new_patients_campaign:,}명",
        f"{new_patient_growth:+.1f}%",
        delta_color="normal",
        help=f"캠페인 기간 중 처음 내원한 고유 환자 수. 비교 기간에는 {new_patients_before:,}명이었습니다."
    )

with col2:
    st.metric(
        "전체 환자 수",
        f"{unique_patients_campaign:,}명",
        f"{patient_growth:+.1f}%",
        delta_color="normal",
        help=f"신환+재진 포함 고유 환자 수. 비교 기간에는 {unique_patients_before:,}명이었습니다."
    )

with col3:
    st.metric(
        "신환 비율",
        f"{new_ratio_campaign:.1f}%",
        f"{new_ratio_change:+.1f}%p",
        delta_color="normal",
        help=f"전체 환자 중 신환이 차지하는 비중. 높을수록 신규 유입이 활발합니다. 비교 기간에는 {new_ratio_before:.1f}%였습니다."
    )

with col4:
    st.metric(
        "인당 진료횟수",
        f"{visits_per_patient_campaign:.1f}회",
        f"{visits_per_patient_change:+.2f}회",
        delta_color="normal",
        help=f"환자 1명이 평균 몇 회 내원했는지를 나타냅니다. 높을수록 재방문이 활발합니다. 비교 기간에는 {visits_per_patient_before:.1f}회였습니다."
    )

# ── 캠페인 순수 효과 ──
if target_regions and len(campaign_non_target) > 0 and len(before_non_target) > 0:
    st.markdown("---")
    st.subheader("캠페인 순수 효과")
    st.caption("타겟 지역의 성장률에서 비타겟 지역(자연 성장)을 차감하여 캠페인으로 인한 순수 증가분만 산출")

    # 타겟 신환
    target_new_campaign = campaign_target[campaign_target['초/재진'] == '신환']['환자번호'].nunique()
    target_new_before = before_target[before_target['초/재진'] == '신환']['환자번호'].nunique()
    target_new_diff = target_new_campaign - target_new_before
    target_new_growth = ((target_new_diff) / target_new_before * 100) if target_new_before > 0 else 0

    # 비타겟 신환
    non_target_new_campaign = campaign_non_target[campaign_non_target['초/재진'] == '신환']['환자번호'].nunique()
    non_target_new_before = before_non_target[before_non_target['초/재진'] == '신환']['환자번호'].nunique()
    non_target_new_diff = non_target_new_campaign - non_target_new_before
    non_target_new_growth = ((non_target_new_diff) / non_target_new_before * 100) if non_target_new_before > 0 else 0

    new_lift = target_new_growth - non_target_new_growth

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(
            "타겟 신환 증가",
            f"{target_new_diff:+,}명",
            f"{target_new_growth:+.1f}%",
            delta_color="normal",
            help=f"캠페인을 집행한 지역의 신환 변화. {target_new_before:,}명 → {target_new_campaign:,}명"
        )
    with col2:
        st.metric(
            "비타겟 신환 증가",
            f"{non_target_new_diff:+,}명",
            f"{non_target_new_growth:+.1f}%",
            delta_color="off",
            help=f"캠페인을 집행하지 않은 지역의 자연 변화(대조군). {non_target_new_before:,}명 → {non_target_new_campaign:,}명"
        )
    with col3:
        st.metric(
            "신환 순수 효과",
            f"{new_lift:+.1f}%p",
            help="타겟 성장률에서 비타겟 성장률을 뺀 값. 양수이면 캠페인이 자연 성장 이상의 효과를 냈다는 의미입니다."
        )

st.markdown("---")

# ── 일별 신환 트렌드 ──
st.subheader("일별 신환 트렌드")

# 캠페인 전후 30일 데이터
trend_start = campaign_start - timedelta(days=30)
trend_end = campaign_end + timedelta(days=30)
trend_data = df[(df['진료일자'] >= pd.to_datetime(trend_start)) & (df['진료일자'] <= pd.to_datetime(trend_end))]

if target_regions:
    trend_data = trend_data[trend_data['행정동'].isin(target_regions)]

# nunique 기반 일별 신환
daily_new = trend_data[trend_data['초/재진'] == '신환'].groupby('진료일자')['환자번호'].nunique().reset_index(name='신환수')
daily_new['7일 이동평균'] = daily_new['신환수'].rolling(window=7, min_periods=1).mean()

# Phase 분류 (전/중/후)
campaign_start_ts = pd.to_datetime(campaign_start)
campaign_end_ts = pd.to_datetime(campaign_end)
daily_new['구간'] = daily_new['진료일자'].apply(
    lambda d: '캠페인 전' if d < campaign_start_ts else ('캠페인 중' if d <= campaign_end_ts else '캠페인 후')
)

# Phase별 일평균 계산
phase_avg = daily_new.groupby('구간')['신환수'].mean()
avg_before = phase_avg.get('캠페인 전', 0)
avg_during = phase_avg.get('캠페인 중', 0)
avg_after = phase_avg.get('캠페인 후', 0)

# Phase 평균선 데이터
phase_lines_data = []
for phase, avg_val in [('캠페인 전', avg_before), ('캠페인 중', avg_during), ('캠페인 후', avg_after)]:
    phase_rows = daily_new[daily_new['구간'] == phase]
    if len(phase_rows) > 0:
        phase_lines_data.append({'구간': phase, '시작': phase_rows['진료일자'].min(), '종료': phase_rows['진료일자'].max(), '일평균': avg_val})

phase_df = pd.DataFrame(phase_lines_data)

# 툴팁용 날짜 문자열 (영어 월명 방지)
daily_new['날짜'] = daily_new['진료일자'].dt.strftime('%Y-%m-%d')

# 차트 레이어
base = alt.Chart(daily_new).encode(
    x=alt.X('진료일자:T', title='날짜', axis=alt.Axis(format='%m-%d'))
)

line = base.mark_line(color='#0072C3', opacity=0.4).encode(
    y=alt.Y('신환수:Q', title='신환 수(명)'),
    tooltip=[alt.Tooltip('날짜:N', title='날짜'), '신환수:Q']
)

ma_line = base.mark_line(color='#0072C3', strokeWidth=2).encode(
    y='7일 이동평균:Q',
    tooltip=[alt.Tooltip('날짜:N', title='날짜'), alt.Tooltip('7일 이동평균:Q', format='.1f')]
)

# 캠페인 기간 음영
campaign_rect = alt.Chart(pd.DataFrame({
    'start': [campaign_start],
    'end': [campaign_end],
    '캠페인 시작': [str(campaign_start)],
    '캠페인 종료': [str(campaign_end)]
})).mark_rect(opacity=0.12, color='#2CA02C').encode(
    x='start:T',
    x2='end:T',
    tooltip=[alt.Tooltip('캠페인 시작:N'), alt.Tooltip('캠페인 종료:N')]
)

# Phase 평균 수평선
phase_color_map = {'캠페인 전': '#A0AEC0', '캠페인 중': '#2CA02C', '캠페인 후': '#E67E22'}
phase_rules = alt.Chart(phase_df).mark_rule(strokeDash=[6, 4], strokeWidth=2).encode(
    x='시작:T',
    x2='종료:T',
    y='일평균:Q',
    color=alt.Color('구간:N',
        scale=alt.Scale(domain=list(phase_color_map.keys()), range=list(phase_color_map.values())),
        legend=alt.Legend(title='구간 일평균')
    ),
    tooltip=[alt.Tooltip('구간:N'), alt.Tooltip('일평균:Q', format='.1f', title='일평균 신환')]
)

# Phase 평균 라벨
phase_labels = alt.Chart(phase_df).mark_text(
    align='left', dx=5, dy=-8, fontSize=13, fontWeight='bold'
).encode(
    x='시작:T',
    y='일평균:Q',
    text=alt.Text('일평균:Q', format='.1f'),
    color=alt.Color('구간:N', scale=alt.Scale(domain=list(phase_color_map.keys()), range=list(phase_color_map.values())), legend=None)
)

chart = (campaign_rect + line + ma_line + phase_rules + phase_labels).properties(
    height=400
).interactive()

st.altair_chart(chart, width='stretch')

# 자동 해석 캡션
if avg_before > 0:
    during_vs_before = (avg_during - avg_before) / avg_before * 100
    after_vs_before = (avg_after - avg_before) / avg_before * 100
    sustain_text = f"종료 후 일평균 {avg_after:.1f}명으로 {'효과 일부 지속' if avg_after > avg_before else '캠페인 전 수준으로 회귀'}."
    st.caption(f"캠페인 기간 일평균 신환 {avg_during:.1f}명 (캠페인 전 {avg_before:.1f}명 대비 {during_vs_before:+.0f}%). {sustain_text}")

st.markdown("---")

# ── 지역별 성과 분석 ──
st.subheader("지역별 성과 분석")

if not target_regions:
    st.info("타겟 지역을 선택하면 더 상세한 분석을 볼 수 있습니다.")

# 지역별 성과 계산 - nunique 기반, 행정동 미입력 제외
campaign_with_dong = campaign_data[campaign_data['행정동'].str.strip().astype(bool)]
before_with_dong = before_data[before_data['행정동'].str.strip().astype(bool)]

region_campaign_patients = campaign_with_dong.groupby('행정동')['환자번호'].nunique().reset_index(name='환자수_캠페인')
region_campaign_new = campaign_with_dong[campaign_with_dong['초/재진'] == '신환'].groupby('행정동')['환자번호'].nunique().reset_index(name='신환수_캠페인')
region_campaign = pd.merge(region_campaign_patients, region_campaign_new, on='행정동', how='outer')

region_before_patients = before_with_dong.groupby('행정동')['환자번호'].nunique().reset_index(name='환자수_이전')
region_before_new = before_with_dong[before_with_dong['초/재진'] == '신환'].groupby('행정동')['환자번호'].nunique().reset_index(name='신환수_이전')
region_before = pd.merge(region_before_patients, region_before_new, on='행정동', how='outer')

region_performance = pd.merge(region_campaign, region_before, on='행정동', how='outer').fillna(0)

region_performance['신환_증가'] = region_performance['신환수_캠페인'] - region_performance['신환수_이전']
region_performance['신환_증가율'] = (region_performance['신환_증가'] / region_performance['신환수_이전'] * 100).replace([np.inf, -np.inf], 0).fillna(0)
region_performance['환자_증가율'] = ((region_performance['환자수_캠페인'] - region_performance['환자수_이전']) / region_performance['환자수_이전'] * 100).replace([np.inf, -np.inf], 0).fillna(0)

# 타겟 지역 표시
region_performance['타겟여부'] = region_performance['행정동'].isin(target_regions)

# ── 차트 1: 신환 증가 TOP 10 + 타겟/비타겟 평균선 ──
st.markdown("**신환 증가 TOP 10**")

top_regions = region_performance.nlargest(10, '신환_증가')[['행정동', '신환수_캠페인', '신환수_이전', '신환_증가', '타겟여부']]

# 타겟/비타겟 평균 증가수
target_perf = region_performance[region_performance['타겟여부']]
non_target_perf = region_performance[~region_performance['타겟여부']]
target_avg_increase = target_perf['신환_증가'].mean() if len(target_perf) > 0 else 0
non_target_avg_increase = non_target_perf['신환_증가'].mean() if len(non_target_perf) > 0 else 0

bars = alt.Chart(top_regions).mark_bar().encode(
    x=alt.X('신환_증가:Q', title='신환 증가수(명)'),
    y=alt.Y('행정동:N', sort='-x', title=''),
    color=alt.Color('타겟여부:N',
                  scale=alt.Scale(domain=[True, False], range=['#FF6B6B', '#4ECDC4']),
                  legend=alt.Legend(title='타겟 지역')),
    tooltip=['행정동',
            alt.Tooltip('신환수_이전:Q', title='비교 기간'),
            alt.Tooltip('신환수_캠페인:Q', title='캠페인 기간'),
            alt.Tooltip('신환_증가:Q', title='증가')]
).properties(height=400)

# 타겟/비타겟 평균 기준선
ref_lines_data = pd.DataFrame([
    {'기준': f'타겟 평균 ({target_avg_increase:+.1f}명)', '값': target_avg_increase, 'color_key': '타겟'},
    {'기준': f'비타겟 평균 ({non_target_avg_increase:+.1f}명)', '값': non_target_avg_increase, 'color_key': '비타겟'}
])
ref_rules = alt.Chart(ref_lines_data).mark_rule(strokeDash=[6, 4], strokeWidth=2).encode(
    x='값:Q',
    color=alt.Color('기준:N',
        scale=alt.Scale(domain=ref_lines_data['기준'].tolist(), range=['#FF6B6B', '#4ECDC4']),
        legend=alt.Legend(title='평균 기준선')),
    tooltip=[alt.Tooltip('기준:N'), alt.Tooltip('값:Q', format='.1f', title='평균 증가')]
)

st.altair_chart(bars + ref_rules, width='stretch')

if target_regions and len(target_perf) > 0:
    diff = target_avg_increase - non_target_avg_increase
    st.caption(f"타겟 지역 평균 신환 증가 {target_avg_increase:+.1f}명 vs 비타겟 {non_target_avg_increase:+.1f}명 (차이: {diff:+.1f}명)")

st.write("")

# ── 차트 2: 타겟 지역별 성과 상세 ──
if target_regions and len(target_perf) > 0:
    st.markdown("**타겟 지역별 성과 상세**")
    st.caption("선택한 타겟 지역별 신환 변화. 다음 캠페인의 지역 선정에 활용하세요.")

    target_detail = target_perf[['행정동', '신환수_이전', '신환수_캠페인', '신환_증가', '신환_증가율']].copy()
    target_detail = target_detail.sort_values('신환_증가', ascending=False)
    target_detail['라벨'] = target_detail.apply(
        lambda r: f"{int(r['신환수_이전'])}→{int(r['신환수_캠페인'])}명 ({r['신환_증가율']:+.0f}%)", axis=1
    )

    detail_bars = alt.Chart(target_detail).mark_bar().encode(
        x=alt.X('신환_증가:Q', title='신환 증가수(명)'),
        y=alt.Y('행정동:N', sort='-x', title=''),
        color=alt.condition(
            alt.datum.신환_증가 > 0,
            alt.value('#FF6B6B'),
            alt.value('#A0AEC0')
        ),
        tooltip=['행정동',
                alt.Tooltip('신환수_이전:Q', title='비교 기간'),
                alt.Tooltip('신환수_캠페인:Q', title='캠페인 기간'),
                alt.Tooltip('신환_증가:Q', title='증가'),
                alt.Tooltip('신환_증가율:Q', format='.1f', title='증가율(%)')]
    ).properties(height=max(len(target_detail) * 40, 200))

    detail_labels = alt.Chart(target_detail).mark_text(
        align='left', dx=5, fontSize=12, fontWeight='bold'
    ).encode(
        x='신환_증가:Q',
        y=alt.Y('행정동:N', sort='-x'),
        text='라벨:N',
        color=alt.value('#333333')
    )

    st.altair_chart(detail_bars + detail_labels, width='stretch')

st.markdown("---")

# ── 신환 분석 ──
if target_regions:
    regions_display = ', '.join(target_regions[:3]) + ('...' if len(target_regions) > 3 else '')
    st.subheader(f"신환 분석 (타겟 지역: {regions_display})")
else:
    st.subheader("신환 분석 (전체 지역)")

# Task 5: 변수명 충돌 해결 — DataFrame은 _df 접미사
if target_regions:
    new_patients_campaign_df = campaign_data[
        (campaign_data['초/재진'] == '신환') &
        (campaign_data['행정동'].isin(target_regions))
    ]
    new_patients_before_df = before_data[
        (before_data['초/재진'] == '신환') &
        (before_data['행정동'].isin(target_regions))
    ]
else:
    new_patients_campaign_df = campaign_data[campaign_data['초/재진'] == '신환']
    new_patients_before_df = before_data[before_data['초/재진'] == '신환']

# 연령대별 구성비 비교
st.markdown("**연령대별 신환 구성비**")

age_campaign = new_patients_campaign_df.drop_duplicates('환자번호').groupby('연령대', observed=True).size().reset_index(name='신환수')
age_before = new_patients_before_df.drop_duplicates('환자번호').groupby('연령대', observed=True).size().reset_index(name='신환수')

campaign_total_age = age_campaign['신환수'].sum()
before_total_age = age_before['신환수'].sum()
age_campaign['구성비'] = (age_campaign['신환수'] / campaign_total_age * 100) if campaign_total_age > 0 else 0
age_before['구성비'] = (age_before['신환수'] / before_total_age * 100) if before_total_age > 0 else 0
age_campaign['기간'] = '캠페인'
age_before['기간'] = '이전'

age_comparison = pd.concat([age_campaign, age_before], ignore_index=True)

chart = alt.Chart(age_comparison).mark_bar().encode(
    x=alt.X('연령대:N', title='연령대', sort=labels, axis=alt.Axis(labelAngle=0)),
    y=alt.Y('구성비:Q', title='구성비 (%)'),
    color=alt.Color('기간:N',
        scale=alt.Scale(domain=['이전', '캠페인'], range=['#A0AEC0', '#FF6B6B']),
        legend=alt.Legend(title='기간')),
    xOffset=alt.XOffset('기간:N', sort=['이전', '캠페인']),
    tooltip=['연령대', '기간', alt.Tooltip('구성비:Q', format='.1f', title='구성비(%)'), alt.Tooltip('신환수:Q', title='신환 수')]
).properties(height=350)

st.altair_chart(chart, width='stretch')

# 구성비 변화 자동 캡션
if campaign_total_age > 0 and before_total_age > 0:
    age_shift = pd.merge(
        age_campaign[['연령대', '구성비']].rename(columns={'구성비': '캠페인_비'}),
        age_before[['연령대', '구성비']].rename(columns={'구성비': '이전_비'}),
        on='연령대', how='outer'
    )
    age_shift[['캠페인_비', '이전_비']] = age_shift[['캠페인_비', '이전_비']].fillna(0)
    age_shift['변화'] = age_shift['캠페인_비'] - age_shift['이전_비']
    top_increase = age_shift.nlargest(1, '변화').iloc[0]
    top_decrease = age_shift.nsmallest(1, '변화').iloc[0]
    st.caption(f"구성비 증가: {top_increase['연령대']} ({top_increase['변화']:+.1f}%p) / 감소: {top_decrease['연령대']} ({top_decrease['변화']:+.1f}%p)")

# 성별 캡션
gender_campaign = new_patients_campaign_df.drop_duplicates('환자번호')['성별'].replace({'M': '남성', 'F': '여성'}).value_counts(normalize=True) * 100
gender_before = new_patients_before_df.drop_duplicates('환자번호')['성별'].replace({'M': '남성', 'F': '여성'}).value_counts(normalize=True) * 100
gender_parts = []
for g in ['남성', '여성']:
    c_val = gender_campaign.get(g, 0)
    b_val = gender_before.get(g, 0)
    gender_parts.append(f"{g} {c_val:.0f}% (이전 {b_val:.0f}%)")
st.caption(f"성별 구성: {' / '.join(gender_parts)}")

st.markdown("---")

# ── 신환 재방문 분석 ──
st.subheader("신환 재방문 분석")

# 캠페인 기간 신환의 환자번호 추출
new_patient_ids = new_patients_campaign_df['환자번호'].unique()

# 비교 기간 신환의 재방문 (delta 계산용)
before_new_patient_ids = new_patients_before_df['환자번호'].unique()
before_after_start = before_end + timedelta(days=1)
before_after_end = before_end + timedelta(days=30)
before_after_data = df[
    (df['진료일자'] >= pd.to_datetime(before_after_start)) &
    (df['진료일자'] <= pd.to_datetime(before_after_end))
]
before_revisits = before_after_data[before_after_data['환자번호'].isin(before_new_patient_ids)]
before_revisit_count = before_revisits.groupby('환자번호').size().reset_index(name='재방문횟수')
before_revisit_rate = len(before_revisit_count) / len(before_new_patient_ids) * 100 if len(before_new_patient_ids) > 0 else 0

# 이후 30일간 재방문 확인
if len(after_data) > 0:
    revisits = after_data[after_data['환자번호'].isin(new_patient_ids)]
    revisit_count = revisits.groupby('환자번호').size().reset_index(name='재방문횟수')

    col1, col2, col3 = st.columns(3)

    with col1:
        revisit_rate = len(revisit_count) / len(new_patient_ids) * 100 if len(new_patient_ids) > 0 else 0
        revisit_delta = revisit_rate - before_revisit_rate
        st.metric("30일 내 재방문율", f"{revisit_rate:.1f}%", f"{revisit_delta:+.1f}%p",
            delta_color="normal",
            help=f"캠페인 신환 중 종료 후 30일 내 1회 이상 재방문한 비율. 높을수록 단골 전환이 잘 되고 있습니다. 비교 기간 신환은 {before_revisit_rate:.1f}%였습니다.")

    with col2:
        avg_revisits = revisit_count['재방문횟수'].mean() if len(revisit_count) > 0 else 0
        before_avg_revisits = before_revisit_count['재방문횟수'].mean() if len(before_revisit_count) > 0 else 0
        avg_revisit_delta = avg_revisits - before_avg_revisits
        st.metric("평균 재방문 횟수", f"{avg_revisits:.1f}회", f"{avg_revisit_delta:+.1f}회",
            delta_color="normal",
            help=f"재방문한 환자들의 평균 방문 횟수. 높을수록 정기 내원으로 이어지고 있습니다. 비교 기간은 {before_avg_revisits:.1f}회였습니다.")

    with col3:
        retention_7d_data = after_data[
            (after_data['환자번호'].isin(new_patient_ids)) &
            (after_data['진료일자'] <= pd.to_datetime(campaign_end + timedelta(days=7)))
        ]
        retention_7d = len(retention_7d_data['환자번호'].unique())
        retention_7d_rate = retention_7d / len(new_patient_ids) * 100 if len(new_patient_ids) > 0 else 0

        before_7d_data = before_after_data[
            (before_after_data['환자번호'].isin(before_new_patient_ids)) &
            (before_after_data['진료일자'] <= pd.to_datetime(before_end + timedelta(days=7)))
        ]
        before_7d_rate = len(before_7d_data['환자번호'].unique()) / len(before_new_patient_ids) * 100 if len(before_new_patient_ids) > 0 else 0
        retention_7d_delta = retention_7d_rate - before_7d_rate
        st.metric("7일 내 재방문율", f"{retention_7d_rate:.1f}%", f"{retention_7d_delta:+.1f}%p",
            delta_color="normal",
            help=f"신환이 7일 내 빠르게 재방문한 비율. 초기 만족도를 나타냅니다. 비교 기간은 {before_7d_rate:.1f}%였습니다.")

    # 재방문 분포
    st.markdown("**재방문 횟수 분포**")

    revisit_dist = revisit_count['재방문횟수'].value_counts().reset_index()
    revisit_dist.columns = ['재방문횟수', '환자수']

    chart3 = alt.Chart(revisit_dist).mark_bar().encode(
        x=alt.X('재방문횟수:O', title='재방문 횟수', axis=alt.Axis(labelAngle=0)),
        y=alt.Y('환자수:Q', title='환자 수'),
        color=alt.value('#0072C3'),
        tooltip=['재방문횟수', '환자수']
    ).properties(height=300)

    st.altair_chart(chart3, width='stretch')

    # 자동 해석 캡션
    total_revisitors = len(revisit_count)
    multi_revisitors = len(revisit_count[revisit_count['재방문횟수'] >= 2])
    multi_rate = multi_revisitors / total_revisitors * 100 if total_revisitors > 0 else 0
    if total_revisitors > 0:
        st.caption(f"재방문 환자 {total_revisitors:,}명 중 {multi_revisitors:,}명({multi_rate:.0f}%)이 2회 이상 방문하여 정기 내원으로 전환되는 추세입니다.")
else:
    st.info("캠페인 종료 후 데이터가 충분하지 않아 재방문 분석을 수행할 수 없습니다.")
