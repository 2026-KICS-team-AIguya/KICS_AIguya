# -*- coding: utf-8 -*-
"""
실측(N=0,4~7) + mock(N=8~30) 결합 -> 3-class(여유/보통/혼잡) 분류 모델 학습.

- 정원(CAPACITY)/등급 경계는 ai/scripts/config.py 참고.
- session(group) 내부 z-score 정규화로 절대 baseline이 아니라 상대 편차를 학습
  (정규화 파라미터는 model_hgb_final.joblib과 함께 session_norm_stats.csv로 저장 —
  실배치 시 새 session의 baseline을 추정하는 calibration 단계에 사용할 것. 자세한 내용은
  ai/docs/01_model_experiment_report.md 4절 참고).
- 평가는 GroupKFold(세션/가상세션 단위) — 랜덤 분할 대비 훨씬 보수적이고 정직한 지표.
  반드시 이 분할 방식을 유지할 것 (랜덤 분할은 leakage로 성능이 부풀려짐).

주의(반드시 docs/01_model_experiment_report.md 같이 읽을 것):
- "보통"/"혼잡" 클래스는 현재 100% synthetic(mock) 데이터뿐이다 — 실측 검증 전까지
  이 두 클래스의 성능 지표를 "실제 정확도"로 보고하면 안 된다.
"""
import os
import pandas as pd
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import GroupKFold
from sklearn.metrics import accuracy_score, f1_score, classification_report, confusion_matrix
from sklearn.utils.class_weight import compute_sample_weight
from sklearn.inspection import permutation_importance
import joblib

import sys
sys.path.insert(0, os.path.dirname(__file__))
from config import FEATURES, CAPACITY, to_level  # noqa: E402

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
REAL_LABELED_PATH = os.path.join(REPO_ROOT, "data", "ai", "labeled_real_final.csv")
MOCK_PATH = os.path.join(REPO_ROOT, "data", "ai", "mock_data_n8_30.csv")
MODEL_OUT_PATH = os.path.join(REPO_ROOT, "data", "ai", "model_hgb_final.joblib")
NORM_STATS_OUT_PATH = os.path.join(REPO_ROOT, "data", "ai", "session_norm_stats.csv")


def load_combined():
    real = pd.read_csv(REAL_LABELED_PATH)
    real = real[~real['possible_session_warmup'].astype(bool)].copy()
    real['group'] = 'real_' + real['session'].astype(str)

    mock = pd.read_csv(MOCK_PATH)
    mock['group'] = mock['session_baseline'].astype(str)

    common = FEATURES + ['n_people', 'group']
    df = pd.concat([real[common], mock[common]], ignore_index=True)
    df['level'] = df['n_people'].apply(lambda n: to_level(n, CAPACITY))
    return df


def normalize_by_group(df):
    """session(group) 내부 z-score. 정규화 통계 자체도 반환(실배치 calibration 참고용)."""
    stats = df.groupby('group')[FEATURES].agg(['mean', 'std'])
    df_norm = df.copy()
    for feat in FEATURES:
        df_norm[feat] = df.groupby('group')[feat].transform(lambda x: (x - x.mean()) / (x.std() + 1e-9))
    return df_norm, stats


def main():
    df = load_combined()
    print("=== 데이터 구성 ===")
    print(df.groupby('level').size())

    df_norm, norm_stats = normalize_by_group(df)
    norm_stats.to_csv(NORM_STATS_OUT_PATH, encoding='utf-8-sig')
    print(f"\nsession 정규화 통계 저장: {NORM_STATS_OUT_PATH}")

    X = df_norm[FEATURES].values
    y = df['level'].values
    groups = df['group'].values
    n_groups = df['group'].nunique()
    print(f"\n고유 group 수: {n_groups}")

    gkf = GroupKFold(n_splits=min(9, n_groups))
    accs, f1s = [], []
    all_true, all_pred = [], []
    for fold, (tr_idx, te_idx) in enumerate(gkf.split(X, y, groups)):
        clf = HistGradientBoostingClassifier(random_state=42, max_iter=200)
        sw = compute_sample_weight('balanced', y[tr_idx])
        clf.fit(X[tr_idx], y[tr_idx], sample_weight=sw)
        pred = clf.predict(X[te_idx])
        acc = accuracy_score(y[te_idx], pred)
        f1 = f1_score(y[te_idx], pred, average='macro')
        accs.append(acc); f1s.append(f1)
        all_true.extend(y[te_idx]); all_pred.extend(pred)
        print(f"fold{fold}: test_groups={sorted(set(groups[te_idx]))} acc={acc:.3f} macroF1={f1:.3f}")

    print(f"\nGroupKFold 평균: acc={np.mean(accs):.3f} macroF1={np.mean(f1s):.3f}")
    print("\n=== 전체 fold 합산 classification_report ===")
    print(classification_report(all_true, all_pred, digits=3))
    print("=== confusion matrix (행=실제, 열=예측) ===")
    labels = ['여유', '보통', '혼잡']
    print(pd.DataFrame(confusion_matrix(all_true, all_pred, labels=labels), index=labels, columns=labels))

    # 최종 모델: 전체 데이터로 fit해서 저장
    clf_full = HistGradientBoostingClassifier(random_state=42, max_iter=200)
    sw_full = compute_sample_weight('balanced', y)
    clf_full.fit(X, y, sample_weight=sw_full)

    perm = permutation_importance(clf_full, X, y, n_repeats=10, random_state=42, scoring='f1_macro')
    imp = pd.Series(perm.importances_mean, index=FEATURES).sort_values(ascending=False)
    print("\n=== Feature importance (permutation, 참고용) ===")
    print(imp)

    joblib.dump(clf_full, MODEL_OUT_PATH)
    print(f"\n최종 모델 저장: {MODEL_OUT_PATH}")


if __name__ == "__main__":
    main()
