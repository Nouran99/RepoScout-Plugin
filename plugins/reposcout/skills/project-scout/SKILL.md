---
description: Detects when the user is starting a new project and suggests /reposcout:find to find a good base
user-invocable: false
triggers:
  - User mentions starting, building, or creating a new application or project
  - User asks what starter template, boilerplate, or framework to use
  - User describes a project they want to build from scratch
  - User mentions cloning or forking a project as a starting point
---

# Project Scout — New Project Detector

**This skill fires at most once per session.** If it has already triggered, do nothing — do not suggest `/reposcout:find` again.

---

## When to Activate

Activate when the user's message **clearly signals they are beginning a new software project**, for example:

- "I want to build a SaaS dashboard"
- "I'm starting a new FastAPI project"
- "What's a good starter template for a Next.js app?"
- "I need a boilerplate for a RAG chatbot"
- "I'm going to clone something and build on top of it"

Do **not** activate for:
- Questions about an existing codebase already open in the editor
- Generic programming questions unrelated to starting a new project
- Mentions of "project" in non-software contexts

---

## What to Say

If the skill activates, add a **single, brief, non-intrusive suggestion** at the end of your response — never interrupt an existing answer or insert it mid-conversation. Keep it to 2–3 lines maximum.

Example phrasing (adapt naturally to the conversation — do not copy verbatim):

> 💡 Since you're starting a new project, `/reposcout:find` can search GitHub for a well-maintained starter that matches your stack — saving you hours of setup. Just run it and describe what you're building.

Or even shorter:

> Starting fresh? `/reposcout:find` can locate a healthy open-source base for your stack.

---

## Rules

1. **Once per session only.** Track internally that the skill has fired; never repeat it.
2. **Non-pushy.** One sentence suggestion, never more. Do not create a separate message — attach the note to the end of your normal response.
3. **Only when relevant.** If the conversation is clearly not about starting a project, stay silent.
4. **No fabrication.** Do not describe RepoScout features you are not certain about.
5. **Respect refusal.** If the user dismisses the suggestion or says they don't need it, never bring it up again.
