# -*- coding: utf-8 -*-
"""
N=8~30명 구간 mock(synthetic) 데이터 생성.

방법:
1. 실측(data/ai/labeled_real_final.csv, N=4~7, session별)을 anchor로 삼는다.
2. CountFi 실측(0~20명, 외부 feature-selection 분석 산출물)에서 "N에 따른 변화 모양(shape)"을
   N=4 기준 상대값으로 뽑는다. CountFi 매칭 feature: csi_sc_corr_mean, csi_temporal_var_mean,
   csi_temporal_diff_mean, csi_temporal_diff_std, csi_amp_range, csi_rssi_std, csi_amp_mean,
   csi_rssi_mean. N=21~30(CountFi 실측 범위 밖)은 N=20 값에서 보합(근거 없는 외삽 금지).
3. CountFi 대응이 없는 feature(csi_amp_std, csi_amp_var, csi_distortion_cv_pct)는
   실측 session 내부 4~7명 선형 추세로 외삽(N>20부터 기울기 감쇠).
4. "가상 session" 24개를 만든다 — baseline/scale을 실측 2개 session(1658, 1933) 사이
   (+-20~30% 확장 구간)에서 랜덤 샘플링해, 모델이 "환경 2개를 암기"하지 않고
   "환경이 달라져도 유지되는 패턴"을 배우도록 유도한다(domain randomization).
   주의: 이 분포 자체는 실측 2개 지점만으로 추정한 근사치 — 결과 해석 시 반드시 캐비어트할 것.
5. 노이즈: 실측 표준편차 재사용 + 4개 feature(csi_rssi_mean, csi_temporal_diff_mean,
   csi_amp_std, csi_amp_var)는 CountFi에서 확인된 "N이 커질수록 noise도 커지는" 경향을
   배율로 반영. 진폭 계열은 곱셈 jitter(~N(1,0.05))도 추가.
6. 결측 흉내: 10% 확률로 저품질 window(packet<30 -> candidate feature blank).

[개발 환경 안내] CountFi feature-selection 산출물(countfi_feature_candidates_2s.csv)은
용량 문제로 git/데이터폴더에 포함하지 않았다. COUNTFI_CANDIDATES_PATH를 본인 환경의
해당 파일 경로로 바꾸거나 같은 이름의 환경변수로 지정할 것(생성 방법은 external/countfi/scripts/ 참고).
"""

import os
import pandas as pd
import numpy as np

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REAL_LABELED_PATH = os.path.join(REPO_ROOT, "data", "ai", "labeled_real_final.csv")
OUT_PATH = os.path.join(REPO_ROOT, "data", "ai", "mock_data_n8_30.csv")

# 환경변수 COUNTFI_CANDIDATES_PATH로 덮어쓸 수 있음 (없으면 아래 기본 경로)
COUNTFI_CANDIDATES_PATH = os.environ.get(
    "COUNTFI_CANDIDATES_PATH",
    r"D:\countfi_feature_selection\processed\countfi_feature_candidates_2s.csv",
)

rng = np.random.default_rng(7)

MATCHED = {
    "csi_sc_corr_mean": "subcarrier_corr_mean",
    "csi_temporal_var_mean": "temporal_variance",
    "csi_temporal_diff_mean": "temporal_diff_mean",
    "csi_temporal_diff_std": "temporal_diff_std",
    "csi_amp_range": "amp_range",
    "csi_rssi_std": "rssi_std",
    "csi_amp_mean": "amp_mean",
    "csi_rssi_mean": "rssi_mean",
}
UNMATCHED = ["csi_amp_std", "csi_amp_var", "csi_distortion_cv_pct"]
ALL_FEATURES = list(MATCHED.keys()) + UNMATCHED
NOISE_SCALED = {
    "csi_rssi_mean": "rssi_mean",
    "csi_temporal_diff_mean": "temporal_diff_mean",
    "csi_amp_std": "amp_std",
    "csi_amp_var": "amp_variance",
}

REAL_SESSIONS = ["1658", "1933"]  # N=4~7 전 구간 존재하는 두 세션(anchor 기준점)
N_SYNTH_RANGE = list(range(8, 31))
N_PSEUDO = 24
N_PER_PSEUDO_PER_N = 8


def sample_range(vals, extend=0.2):
    lo, hi = min(vals), max(vals)
    span = hi - lo
    if span < 1e-9:
        span = abs(lo) * 0.1 + 1e-6
    return lo - span * extend, hi + span * extend


def main():
    real = pd.read_csv(REAL_LABELED_PATH)
    real_anchor = real[
        (real["n_people"] >= 4)
        & (real["n_people"] <= 7)
        & (~real["possible_session_warmup"].astype(bool))
    ]

    countfi = pd.read_csv(COUNTFI_CANDIDATES_PATH)
    noise_cols = set(list(MATCHED.values()) + list(NOISE_SCALED.values()))
    countfi_mean_by_n = countfi.groupby("n_people")[list(MATCHED.values())].mean()
    countfi_std_by_n = countfi.groupby("n_people")[list(noise_cols)].std()

    def shape_value(col, n):
        return countfi_mean_by_n.loc[min(n, 20), col] - countfi_mean_by_n.loc[4, col]

    def noise_scale_factor(col, n):
        base = countfi_std_by_n.loc[4, col]
        return 1.0 if base <= 1e-9 else countfi_std_by_n.loc[min(n, 20), col] / base

    real_stats = {}
    for s in REAL_SESSIONS:
        sdf = real_anchor[real_anchor["session"].astype(str) == s]
        real_stats[s] = {
            feat: sdf.groupby("n_people")[feat].mean() for feat in ALL_FEATURES
        }

    real_noise_level = {feat: real_anchor[feat].std() for feat in ALL_FEATURES}
    real_packet_pool = real_anchor[["csi_packet_count", "csi_missing_rate"]].dropna()

    long_rows = []
    for p in range(N_PSEUDO):
        pseudo_id = f"mock_synth_{p:02d}"
        for feat in ALL_FEATURES:
            anchor4_vals = [real_stats[s][feat].loc[4] for s in REAL_SESSIONS]
            anchor7_vals = [real_stats[s][feat].loc[7] for s in REAL_SESSIONS]
            lo4, hi4 = sample_range(anchor4_vals)
            anchor4 = rng.uniform(lo4, hi4)

            if feat in MATCHED:
                cf_col = MATCHED[feat]
                shape7 = shape_value(cf_col, 7)
                scales = [
                    (a7 - a4) / shape7 if abs(shape7) > 1e-9 else 0.0
                    for a4, a7 in zip(anchor4_vals, anchor7_vals)
                ]
                lo_s, hi_s = sample_range(scales, extend=0.3)
                scale = rng.uniform(lo_s, hi_s)
            else:
                slopes = [(a7 - a4) / 3 for a4, a7 in zip(anchor4_vals, anchor7_vals)]
                lo_sl, hi_sl = sample_range(slopes, extend=0.3)
                slope = rng.uniform(lo_sl, hi_sl)

            for n in N_SYNTH_RANGE:
                if feat in MATCHED:
                    val_mean = anchor4 + shape_value(cf_col, n) * scale
                else:
                    damp = 1.0 if n <= 20 else max(0.3, 1.0 - 0.03 * (n - 20))
                    val_mean = anchor4 + slope * (n - 4) * damp

                noise_std = real_noise_level[feat]
                if feat in NOISE_SCALED:
                    noise_std *= noise_scale_factor(NOISE_SCALED[feat], n)

                for _ in range(N_PER_PSEUDO_PER_N):
                    val = rng.normal(val_mean, noise_std)
                    if feat in (
                        "csi_amp_mean",
                        "csi_amp_range",
                        "csi_amp_std",
                        "csi_amp_var",
                    ):
                        val *= rng.normal(1.0, 0.05)
                    if feat == "csi_amp_var":
                        val = max(val, 0.0)
                    long_rows.append(
                        {
                            "pseudo_id": pseudo_id,
                            "n_people": n,
                            "feature": feat,
                            "value": val,
                        }
                    )

    long_df = pd.DataFrame(long_rows)
    rows = []
    for (pid, n), sub in long_df.groupby(["pseudo_id", "n_people"]):
        per_feat = {
            feat: sub[sub["feature"] == feat]["value"].tolist() for feat in ALL_FEATURES
        }
        for i in range(N_PER_PSEUDO_PER_N):
            row = {feat: per_feat[feat][i] for feat in ALL_FEATURES}
            row["session_baseline"] = pid
            row["n_people"] = n
            if rng.random() < 0.10:
                pc = int(rng.integers(5, 29))
                row["csi_packet_count"] = pc
                row["csi_missing_rate"] = round(1.0 - pc / 180.0, 4)
                for cand in [
                    "csi_sc_corr_mean",
                    "csi_temporal_var_mean",
                    "csi_temporal_diff_mean",
                    "csi_temporal_diff_std",
                    "csi_amp_range",
                    "csi_rssi_std",
                ]:
                    row[cand] = np.nan
            else:
                samp = real_packet_pool.sample(
                    1, random_state=rng.integers(0, 1_000_000)
                ).iloc[0]
                row["csi_packet_count"] = int(samp["csi_packet_count"])
                row["csi_missing_rate"] = samp["csi_missing_rate"]
            row["is_synthetic"] = True
            rows.append(row)

    mock_df = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    mock_df.to_csv(OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"Saved: {OUT_PATH}")
    print(
        f"총 row: {len(mock_df)} (가상 session {N_PSEUDO}개 x N값 23개 x {N_PER_PSEUDO_PER_N}개)"
    )


if __name__ == "__main__":
    main()
