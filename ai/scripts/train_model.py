# -*- coding: utf-8 -*-
"""
실측(N=0,4~7) + mock(N=0~30) 결합 -> 3-class(여유/보통/혼잡) 분류 모델 학습.

- 정원(CAPACITY)/등급 경계는 ai/scripts/config.py 참고.
- 정규화는 실서비스(ai/main.py update())와 똑같이 한다: session마다 시작 후 첫
  CALIBRATION_WINDOWS개 유효 window(빈 방 또는 소수 인원)로 baseline을 잡고
  config.fit_baseline / apply_baseline으로 z-score 변환. 학습과 추론이 같은 함수를 쓴다.
  (이전 버전은 session 전체 통계로 정규화해 추론과 기준이 달랐고, 8명을 "혼잡", 30명을
  "여유"로 예측하는 문제가 있었다.)
- 실측은 warmup 의심 구간을 뺀 뒤 timestamp 순 첫 유효 window로 baseline을 잡는다.
  실서비스도 센서를 켜고 충분히 안정화한 뒤 calibration을 시작해야 한다.
- 평가는 GroupKFold(세션/가상세션 단위) — 랜덤 분할 대비 훨씬 보수적이고 정직한 지표.
  반드시 이 분할 방식을 유지할 것 (랜덤 분할은 leakage로 성능이 부풀려짐).

주의(반드시 docs/01_model_experiment_report.md 같이 읽을 것):
- "보통"/"혼잡" 클래스는 현재 100% synthetic(mock) 데이터뿐이다 — 실측 검증 전까지
  이 두 클래스의 성능 지표를 "실제 정확도"로 보고하면 안 된다.
"""

import os
import sys

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    classification_report,
    confusion_matrix,
)
from sklearn.utils.class_weight import compute_sample_weight
from sklearn.inspection import permutation_importance

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import (  # noqa: E402
    CALIBRATION_WINDOWS,
    CAPACITY,
    FEATURES,
    LEVELS,
    apply_baseline,
    fit_baseline,
    to_level,
)

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REAL_LABELED_PATH = os.path.join(REPO_ROOT, "data", "ai", "labeled_real_final.csv")
MOCK_PATH = os.path.join(REPO_ROOT, "data", "ai", "mock_data_n0_30.csv")
MODEL_OUT_PATH = os.path.join(REPO_ROOT, "data", "ai", "model_hgb_final.joblib")
NORM_STATS_OUT_PATH = os.path.join(REPO_ROOT, "data", "ai", "session_norm_stats.csv")


def load_combined():
    """실측 + mock을 합치고 group(session)마다 calibration 구간을 표시한다.

    추론은 결측 window를 건너뛰므로(skipped) 학습에서도 FEATURES 결측 행은 뺀다.
    """
    real = pd.read_csv(REAL_LABELED_PATH)
    real = real[~real["possible_session_warmup"].astype(bool)]
    real = real.dropna(subset=FEATURES).sort_values(["session", "timestamp"]).copy()
    real["group"] = "real_" + real["session"].astype(str)
    # 실서비스와 같이 session 시작 후 첫 CALIBRATION_WINDOWS개 유효 window가 calibration
    real["is_calibration"] = real.groupby("group").cumcount() < CALIBRATION_WINDOWS

    mock = pd.read_csv(MOCK_PATH).dropna(subset=FEATURES).copy()
    mock["group"] = mock["session_baseline"].astype(str)

    common = FEATURES + ["n_people", "group", "is_calibration"]
    df = pd.concat([real[common], mock[common]], ignore_index=True)
    df["is_calibration"] = df["is_calibration"].astype(bool)
    df["level"] = df["n_people"].apply(lambda n: to_level(n, CAPACITY))
    return df


def normalize_by_calibration(df):
    """group마다 calibration 구간으로 baseline을 잡아 z-score 변환 (ai/main.py update()와 동일)."""
    df_norm = df.copy()
    stats = []
    for group, gdf in df.groupby("group"):
        calib = gdf[gdf["is_calibration"]]
        mean, std = fit_baseline(calib[FEATURES].values)
        df_norm.loc[gdf.index, FEATURES] = apply_baseline(
            gdf[FEATURES].values, mean, std
        )
        row = {"group": group, "calib_start_n": int(calib["n_people"].mode().iloc[0])}
        row.update({f"{f}_mean": m for f, m in zip(FEATURES, mean)})
        row.update({f"{f}_std": v for f, v in zip(FEATURES, std)})
        stats.append(row)
    return df_norm, pd.DataFrame(stats)


def print_level_by_n(n_people, pred):
    """인원수별 예측 등급 비율(%). 인원이 늘수록 여유 -> 보통 -> 혼잡으로 올라가야 정상."""
    table = pd.crosstab(
        pd.Series(n_people, name="인원"),
        pd.Series(pred, name="예측"),
        normalize="index",
    ).reindex(columns=LEVELS, fill_value=0.0)
    expected = pd.Series(
        [to_level(n, CAPACITY) for n in table.index], index=table.index, name="정답"
    )
    print(pd.concat([expected, (table * 100).round().astype(int)], axis=1).to_string())


def main():
    df = load_combined()
    print("=== 데이터 구성 ===")
    print(df.groupby("level").size())

    df_norm, norm_stats = normalize_by_calibration(df)
    norm_stats.to_csv(NORM_STATS_OUT_PATH, index=False, encoding="utf-8-sig")
    print(f"\nsession calibration 통계 저장: {NORM_STATS_OUT_PATH}")

    X = df_norm[FEATURES].values
    y = df["level"].values
    groups = df["group"].values
    n_groups = df["group"].nunique()
    print(f"\n고유 group 수: {n_groups}")

    gkf = GroupKFold(n_splits=min(9, n_groups))
    accs, f1s = [], []
    all_true, all_pred, all_n, all_group = [], [], [], []
    for fold, (tr_idx, te_idx) in enumerate(gkf.split(X, y, groups)):
        clf = HistGradientBoostingClassifier(random_state=42, max_iter=200)
        sw = compute_sample_weight("balanced", y[tr_idx])
        clf.fit(X[tr_idx], y[tr_idx], sample_weight=sw)
        pred = clf.predict(X[te_idx])
        acc = accuracy_score(y[te_idx], pred)
        f1 = f1_score(y[te_idx], pred, average="macro")
        accs.append(acc)
        f1s.append(f1)
        all_true.extend(y[te_idx])
        all_pred.extend(pred)
        all_n.extend(df["n_people"].values[te_idx])
        all_group.extend(groups[te_idx])
        print(
            f"fold{fold}: test_groups={sorted(set(groups[te_idx]))} acc={acc:.3f} macroF1={f1:.3f}"
        )

    print(f"\nGroupKFold 평균: acc={np.mean(accs):.3f} macroF1={np.mean(f1s):.3f}")
    print("\n=== 전체 fold 합산 classification_report ===")
    print(classification_report(all_true, all_pred, digits=3))
    print("=== confusion matrix (행=실제, 열=예측) ===")
    print(
        pd.DataFrame(
            confusion_matrix(all_true, all_pred, labels=LEVELS),
            index=LEVELS,
            columns=LEVELS,
        )
    )

    all_n, all_pred = np.array(all_n), np.array(all_pred)
    is_real = np.array([str(g).startswith("real_") for g in all_group])
    print("\n=== [mock, 테스트 fold] 인원수별 예측 비율(%) ===")
    print_level_by_n(all_n[~is_real], all_pred[~is_real])
    print("\n=== [실측, 테스트 fold] 인원수별 예측 비율(%) ===")
    print_level_by_n(all_n[is_real], all_pred[is_real])

    # 최종 모델: 전체 데이터로 fit해서 저장
    clf_full = HistGradientBoostingClassifier(random_state=42, max_iter=200)
    sw_full = compute_sample_weight("balanced", y)
    clf_full.fit(X, y, sample_weight=sw_full)

    perm = permutation_importance(
        clf_full, X, y, n_repeats=10, random_state=42, scoring="f1_macro"
    )
    imp = pd.Series(perm.importances_mean, index=FEATURES).sort_values(ascending=False)
    print("\n=== Feature importance (permutation, 참고용) ===")
    print(imp)

    joblib.dump(clf_full, MODEL_OUT_PATH)
    print(f"\n최종 모델 저장: {MODEL_OUT_PATH}")


if __name__ == "__main__":
    main()
