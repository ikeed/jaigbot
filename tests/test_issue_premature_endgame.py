from app.services.coach_post import EndGameDetector

def test_premature_endgame_trigger_literature_home():
    """
    Test that 'Having that information to take home would really help' 
    does NOT trigger endgame by itself.
    """
    reply = "Having that information to take home would really help."
    result = EndGameDetector.detect(reply)
    
    # This currently fails (returns {'reason': 'followup_literature'})
    assert result is None, f"Expected None, but got {result}"

def test_endgame_trigger_followup_and_literature():
    """
    Test that explicitly mentioning both follow-up AND literature DOES trigger endgame.
    """
    reply = "I'll take the information home and we can talk about it at the next appointment."
    result = EndGameDetector.detect(reply)
    assert result is not None
    assert result["reason"] == "followup_literature"

def test_endgame_trigger_accepted_now():
    """
    Test that 'let's go ahead' still triggers endgame.
    """
    reply = "Okay, yes. I'm still a bit nervous, but knowing I'll have that information and can call if I need to helps a lot. I want to do what's best for Sophia, so let's go ahead."
    result = EndGameDetector.detect(reply)
    assert result is not None
    assert result["reason"] == "accepted_now"
