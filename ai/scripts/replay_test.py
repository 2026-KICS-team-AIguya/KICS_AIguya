# -*- coding: utf-8 -*-
"""
센서 없이 CongestionPredictor.update()를 검증하는 리플레이 테스트.

실측 라벨 데이터(data/ai/labeled_real_final.csv)를 session별로 5초 스트림처럼 한 행씩 update()에 흘려보내고
calibrating -> ok 전환, 결측 행 skipped 처리, 예측 등급 분포를 확인한다.
백엔드 담당자도 이 스크립트를 참고해 센서 없이 서버 연동을 테스트할 수 있다.

주의: 실측은 N=0, 4~7명뿐이라 정원 30 기준 정답이 전부 "여유"다.
      이 테스트는 "정확도 평가"가 아니라 "인터페이스가 멈추지 않고 동작하는지" 확인용이다.
"""
import os
import sys
from collections import Counter

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from main import CongestionPredictor, REPO_ROOT  # noqa: E402
from config import to_level  # noqa: E402

REAL_LABELED_PATH = os.path.join(REPO_ROOT, "data", "ai", "labeled_real_final.csv")


def main():
    df = pd.read_csv(REAL_LABELED_PATH).sort_values(["session", "timestamp"])
    predictor = CongestionPredictor()

    first = df.iloc[0].to_dict()
    predictor.check_schema(first)
    print("check_schema 통과\n")

    for session, sdf in df.groupby("session"):
        status_count = Counter()
        pairs = []
        for row in sdf.to_dict("records"):
            row["link_id"] = f"session_{session}"  # session마다 다른 환경으로 보고 calibration을 따로 잡는다
            result = predictor.update(row)
            status_count[result["status"]] += 1
            if result["status"] == "ok":
                pairs.append((to_level(row["n_people"]), result["level"]))

        print(f"=== session {session} (행 {len(sdf)}개) ===")
        print(f"status: {dict(status_count)}")
        if pairs:
            ct = pd.crosstab(pd.Series([p[0] for p in pairs], name="정답"), pd.Series([p[1] for p in pairs], name="예측"))
            print(ct)
        print()


if __name__ == "__main__":
    main()
