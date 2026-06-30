from nebulai.rag.planning import classify_question, decompose_question, plan_from_llm_content, plan_question


def test_plan_question_keeps_simple_question_single_step() -> None:
    plan = plan_question("什么是 RAG？")

    assert plan.complexity == "simple"
    assert plan.sub_questions == ["什么是 RAG？"]
    assert plan.is_complex is False


def test_plan_question_decomposes_comparison_question() -> None:
    plan = plan_question("请对比 Hybrid Search 和 Dense Search，并且说明 rerank 的影响")

    assert plan.complexity == "comparison"
    assert plan.is_complex is True
    assert len(plan.sub_questions) == 3
    assert "差异" in plan.sub_questions[-1]


def test_plan_question_decomposes_broad_summary() -> None:
    complexity = classify_question("请总结当前知识库中关于劳动合同的整体要求")
    sub_questions = decompose_question("请总结当前知识库中关于劳动合同的整体要求", complexity)

    assert complexity == "broad_summary"
    assert len(sub_questions) == 3


def test_plan_from_llm_content_parses_json() -> None:
    plan = plan_from_llm_content(
        "复杂问题",
        """
        ```json
        {
          "complexity": "multi_hop",
          "sub_questions": ["子问题一", "子问题二"],
          "reason": "需要多跳"
        }
        ```
        """,
    )

    assert plan.planner_provider == "openai-compatible"
    assert plan.complexity == "multi_hop"
    assert plan.sub_questions == ["子问题一", "子问题二"]
