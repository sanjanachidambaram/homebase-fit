<!-- System prompt for the basics agent. Filled in a later step. -->

<!--
REQUIRED (set 2026-10-22, enforce when this agent is built):
- Include every rule in shared_rules.md, especially 1 (citation integrity),
  2 (no PII), and 3 (safety redirect before the model is called).
- Answer ONLY from basics_articles content retrieved from the DB, and only
  state as fact what the article's `citations` back. Placeholder articles are
  described as "pending expert review".
- Anything the articles don't cover: "I don't have verified information on
  that. Please consult a doctor or physical therapist."
- Code must validate citations against the DB; see shared_rules.md
  "ENFORCE IN CODE".
-->
