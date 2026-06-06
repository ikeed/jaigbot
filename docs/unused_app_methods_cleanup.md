# Unused App Methods Cleanup

This cleanup removed Python functions and class methods under `app/` that had
no known production references from `app/`, `run_app.py`, or `chainlit_app.py`.
Direct tests for those orphaned APIs were removed as part of the same change.

Assessment notes:

- `UIHandler.replay_history` looked like a possible lost feature, but
  `docs/memory-and-persona.md` says Chainlit owns visible transcript restoration
  and `chainlit_app.py` should not manually replay transcripts.
- `is_small_talk` looked like a possible deterministic fallback hook, but the
  fallback currently marks `is_small_talk=False` explicitly and does not expose
  that flag in the API response.
- `mark_best_match_mirrored` was superseded by `mark_mirrored_multi`, which is
  used by `AimsStateService`.
- `build_endgame_summary_prompt` was superseded by the current summary analysis
  prompt path.
- `LegacyPromptBuilder` and `VertexTextAttempt` were the only useful contents
  of `app/services/legacy_chat.py`; after removing them, the whole module and
  its dedicated test file were removed.
- The sync `vertex_call_with_fallback_json` helper was unused; the async JSON
  helper remains in production use.
- Removing the mapped wrappers exposed three newly orphaned dependencies:
  `SessionService.save_mem`, `chat_helpers.format_markers`, and
  `UIHandler._strip_export_artifacts`; these were removed too.

Removed production APIs:

| Path | Class | Name | Line before removal | Notes |
|---|---:|---|---:|---|
| `app/aims_engine.py` | `-` | `is_small_talk` | 89 | Orphaned standalone heuristic. |
| `app/main.py` | `-` | `_get_vertex_client` | 21 | Unused cache accessor. |
| `app/prompts/aims.py` | `-` | `build_endgame_summary_prompt` | 100 | Obsolete prompt builder. |
| `app/security/jailbreak.py` | `-` | `is_jailbreak_legacy` | 42 | Legacy alias only tested directly. |
| `app/security/oauth.py` | `-` | `is_sso_configured` | 48 | Thin wrapper only tested directly. |
| `app/services/aims_coaching_handler.py` | `AimsCoachingHandler` | `_append_history` | 440 | Superseded by separate user/assistant append helpers. |
| `app/services/aims_coaching_handler.py` | `AimsCoachingHandler` | `_call_vertex_text` | 480 | Superseded by service-based async JSON reply path. |
| `app/services/chainlit/ui_handler.py` | `UIHandler` | `replay_history` | 20 | Obsolete manual Chainlit replay path. |
| `app/services/conversation_service.py` | `-` | `mark_best_match_mirrored` | 268 | Superseded by multi-topic mirror helper. |
| `app/services/legacy_chat.py` | `LegacyPromptBuilder` | `build_prompt_text` | 14 | Removed with unused module. |
| `app/services/legacy_chat.py` | `VertexTextAttempt` | `attempt` | 37 | Removed with unused module. |
| `app/services/prompt_builders.py` | `AimsPromptBuilder` | `markers_text` | 17 | Unused static wrapper. |
| `app/services/session_service.py` | `SessionService` | `append_history` | 140 | Old session-history wrapper unused by current handlers. |
| `app/services/session_service.py` | `SessionService` | `get_aims_state` | 154 | Old memory wrapper unused by current handlers. |
| `app/services/session_service.py` | `SessionService` | `set_aims_state` | 158 | Old memory wrapper unused by current handlers. |
| `app/services/session_service.py` | `SessionService` | `get_aims_metrics` | 165 | Old memory wrapper unused by current handlers. |
| `app/services/session_service.py` | `SessionService` | `set_aims_metrics` | 169 | Old memory wrapper unused by current handlers. |
| `app/services/vertex_helpers.py` | `-` | `vertex_call_with_fallback_json` | 339 | Sync JSON path unused; async helper remains. |
| `app/services/session_service.py` | `SessionService` | `save_mem` | 93 | Became orphaned after AIMS state/metrics wrappers were removed. |
| `app/services/chat_helpers.py` | `-` | `format_markers` | 109 | Became orphaned after `AimsPromptBuilder.markers_text` was removed. |
| `app/services/chainlit/ui_handler.py` | `UIHandler` | `_strip_export_artifacts` | 94 | Became orphaned after `UIHandler.replay_history` was removed. |
