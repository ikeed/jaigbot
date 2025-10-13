from app.services.coach_post import EndGameDetector


def test_does_not_trigger_on_conditional_if_go_ahead_question():
    text = (
        "Okay, that makes sense when you put it that way. I guess I never thought about all the germs "
        "he's exposed to just by crawling on the floor and putting everything in his mouth. So it’s not really "
        "overwhelming him, it's more like a specific lesson for his immune system. I am feeling better about it. "
        "If we do go ahead with it today, what are the common side effects we should expect?"
    )
    res = EndGameDetector.detect(text)
    assert res is None, "Conditional question about going ahead today should not trigger acceptance"
