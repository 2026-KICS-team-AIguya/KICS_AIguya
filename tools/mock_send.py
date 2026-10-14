"""기존 실행 경로용 CSI 인공 입력 전송기. 정확도 평가에는 사용하지 않는다."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pipeline.replay import main

if __name__ == "__main__":
    if "--feature-file" not in sys.argv and "--synthetic" not in sys.argv:
        sys.argv.append("--synthetic")
    main()
