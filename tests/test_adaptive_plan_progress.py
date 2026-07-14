from app.adaptive_plan_progress import adaptive_plan_progress_teaser_caption


def test_adaptive_plan_progress_teaser_handles_placeholder_concept() -> None:
    caption = adaptive_plan_progress_teaser_caption(
        plan_override={
            "blocks": [
                {
                    "type": "new",
                    "concept": "general",
                }
            ]
        }
    )

    assert caption == "Adaptive plan: следующий акцент — Новая тема"
