"""Tests for the rule-based response engine."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.rule_engine import RuleEngine


engine = RuleEngine()


def content(result):
    """Extract response content from (content, function_name) tuple."""
    return result[0] if result else None


def func(result):
    """Extract function name from (content, function_name) tuple."""
    return result[1] if result else None


# ── BMI Tests ───────────────────────────────────────────────────────

class TestBMI:
    def test_bmi_with_cm_kg_markers(self):
        result = engine.try_respond("키 175cm 몸무게 70kg BMI 알려줘", "healthcare")
        assert result is not None
        assert "22.9" in content(result)
        assert "정상" in content(result)
        assert func(result) == "BMI 계산기"

    def test_bmi_with_numbers_only(self):
        result = engine.try_respond("175 70 bmi", "healthcare")
        assert result is not None
        assert "BMI" in content(result)

    def test_bmi_three_numbers_with_markers(self):
        """25살 170cm 70kg - should correctly extract height and weight, not age."""
        result = engine.try_respond("25살 170cm 70kg bmi 계산해줘", "healthcare")
        assert result is not None
        assert "170" in content(result)
        assert "70" in content(result)

    def test_bmi_missing_data(self):
        result = engine.try_respond("내 bmi 알려줘", "healthcare")
        assert result is not None
        assert "키와 몸무게" in content(result)

    def test_bmi_out_of_range_falls_to_llm(self):
        result = engine.try_respond("키 10cm 몸무게 5kg bmi", "healthcare")
        assert result is None  # Falls through to LLM

    def test_bmi_obese(self):
        """170cm 80kg = BMI 27.7 = 비만"""
        result = engine.try_respond("키 170cm 몸무게 80kg bmi", "healthcare")
        assert result is not None
        assert "비만" in content(result)

    def test_bmi_overweight(self):
        """170cm 72kg = BMI 24.9 = 과체중"""
        result = engine.try_respond("키 170cm 몸무게 72kg bmi", "healthcare")
        assert result is not None
        assert "과체중" in content(result)

    def test_bmi_underweight(self):
        result = engine.try_respond("키 170cm 몸무게 45kg bmi", "healthcare")
        assert result is not None
        assert "저체중" in content(result)


# ── Calorie Tests ───────────────────────────────────────────────────

class TestCalorie:
    def test_single_food(self):
        result = engine.try_respond("라면 칼로리 알려줘", "healthcare")
        assert result is not None
        assert "500 kcal" in content(result)
        assert func(result) == "칼로리 조회"

    def test_kimbap_no_overlap_with_bap(self):
        """김밥 should NOT also match 밥."""
        result = engine.try_respond("김밥 칼로리", "healthcare")
        assert result is not None
        assert "김밥 1줄" in content(result)
        assert "밥 1공기" not in content(result)

    def test_multiple_foods(self):
        result = engine.try_respond("라면이랑 콜라 칼로리", "healthcare")
        assert result is not None
        assert "500 kcal" in content(result)  # 라면
        assert "140 kcal" in content(result)  # 콜라

    def test_unknown_food_falls_to_llm(self):
        result = engine.try_respond("스테이크 칼로리 알려줘", "healthcare")
        assert result is None

    def test_no_calorie_keyword(self):
        result = engine.try_respond("라면 먹고 싶다", "healthcare")
        assert result is None


# ── FAQ Tests ───────────────────────────────────────────────────────

class TestFAQ:
    def test_intermittent_fasting(self):
        result = engine.try_respond("간헐적 단식이 뭐야?", "healthcare")
        assert result is not None
        assert "16:8" in content(result)
        assert func(result) == "건강 FAQ"

    def test_water_intake(self):
        result = engine.try_respond("하루 물 얼마나 마셔야 해?", "healthcare")
        assert result is not None
        assert "1.5~2리터" in content(result)

    def test_sleep_hours(self):
        result = engine.try_respond("수면 시간 어떻게 돼?", "healthcare")
        assert result is not None
        assert "7-9시간" in content(result)

    def test_protein_intake(self):
        result = engine.try_respond("단백질 얼마나 먹어야 해?", "healthcare")
        assert result is not None
        assert "체중 1kg당" in content(result)

    def test_bmr(self):
        result = engine.try_respond("기초대사량이 뭐야?", "healthcare")
        assert result is not None
        assert "최소 에너지량" in content(result)


# ── Greeting Tests ──────────────────────────────────────────────────

class TestGreeting:
    def test_hello(self):
        result = engine.try_respond("안녕", "healthcare")
        assert result is not None
        assert "안녕하세요" in content(result)
        assert func(result) == "인사말"

    def test_long_message_not_greeting(self):
        result = engine.try_respond("안녕하세요 저는 요즘 허리가 아파서 걱정입니다", "healthcare")
        assert result is None


# ── Domain Filter Tests ─────────────────────────────────────────────

class TestDomainFilter:
    def test_movie_domain_returns_none(self):
        result = engine.try_respond("bmi 170 70", "movie")
        assert result is None

    def test_unknown_domain_returns_none(self):
        result = engine.try_respond("안녕", "unknown")
        assert result is None


# ── Complex Queries Fall Through ────────────────────────────────────

class TestFallthrough:
    def test_complex_health_question(self):
        result = engine.try_respond("요즘 무릎이 아프고 계단 오를 때 통증이 심한데 어떻게 해야 할까요?", "healthcare")
        assert result is None

    def test_personalized_advice(self):
        result = engine.try_respond("제가 당뇨가 있는데 운동 루틴 추천해주세요", "healthcare")
        assert result is None


# ── Function Name Tests ─────────────────────────────────────────────

class TestFunctionNames:
    def test_all_functions_return_correct_names(self):
        cases = [
            ("키 170cm 몸무게 70kg bmi", "BMI 계산기"),
            ("라면 칼로리", "칼로리 조회"),
            ("간헐적 단식이 뭐야", "건강 FAQ"),
            ("안녕", "인사말"),
        ]
        for msg, expected_func in cases:
            result = engine.try_respond(msg, "healthcare")
            assert result is not None, f"Expected result for: {msg}"
            assert func(result) == expected_func, f"Expected '{expected_func}' for '{msg}', got '{func(result)}'"
