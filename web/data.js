"use strict";

// Add new buildings here. Scene coordinates are illustrative, not geographic.
const CAMPUS_LOCATIONS = [
  {
    id: "sangnok", name: "상록원", description: "학생식당 · 식음료 매장", detail: "1–3층", mode: "demo",
    source: "https://www.dongguk.edu/page/202",
    geometry: { x: -95, y: 65, width: 108, depth: 76, height: 48 },
    facilities: ["1층 식음료 매장", "2층 학생식당(푸드코트)", "3층 교직원식당"],
    menuSource: "https://dgucoop.dongguk.edu:44649/store/store.php?w=4&l=2",
    kiosk: {
      scope: "상록원 전체", recent: 42, previous: 24,
      pattern: [1, 0, 1, 2, 0, 1, 1, 0, 2, 1],
    },
    floors: [
      {
        id: 1, name: "식음료 매장", shortName: "식음료 매장", waitLabel: "매장별 주문 대기",
        initialOccupancy: [18, 24, 31, 39],
        history: [18, 19, 22, 26, 32, 35, 38, 36, 31, 28, 25, 27],
        dining: [["분식당", "분식류"], ["솥앤누들", "솥밥 및 면류"], ["노브랜드버거/포트캔커피", "패스트푸드·음료"]],
        amenities: "쿱스켓상록원점(유·무인운영), 문구점, 기획사",
      },
      {
        id: 2, name: "학생식당", shortName: "학생식당 · 푸드코트", waitLabel: "예상 배식 대기",
        initialOccupancy: [42, 58, 76, 48],
        history: [27, 31, 39, 46, 58, 65, 72, 76, 70, 64, 60, 58],
        dining: [["학생식당(푸드코트)", "국밥, 덮밥, 파스타 등"]], amenities: null,
      },
      {
        id: 3, name: "교직원식당", shortName: "교직원식당", waitLabel: "예상 배식 대기",
        initialOccupancy: [72, 82, 91, 79],
        history: [42, 47, 56, 65, 71, 78, 86, 90, 88, 85, 83, 82],
        dining: [["교직원식당", "한그릇 등"]], amenities: null,
      },
    ],
  },
  {
    id: "dormitory", name: "기숙사 식당", description: "남산학사", detail: "층 정보 확인 예정", mode: "pending",
    source: "https://dorm.dongguk.edu/main",
    menuSource: "https://dorm.dongguk.edu/article/food/list",
    geometry: { x: -170, y: -135, width: 76, depth: 82, height: 108 },
    facilities: ["남산학사 기숙사식당"], floors: [],
  },
  {
    id: "business", name: "경영관", description: "웰스토리", detail: "지하 2층", mode: "pending",
    source: "https://www.dongguk.edu/page/202",
    menuSource: "https://www.dongguk.edu/article/FOODDFLEX/list",
    geometry: { x: 135, y: -75, width: 104, depth: 74, height: 65 },
    facilities: ["지하 2층 웰스토리", "커피전문점(PAUL BASSET)", "야외 메가MGC커피"], floors: [],
  },
];
