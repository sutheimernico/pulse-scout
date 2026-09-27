"""Every prompt in one file, so that "what did we actually ask the model?" is one place.

Two things govern what is written here.

**Who the reader is.** Taken from `PROJECT.md` §3 and decision D7: a fullstack developer with a
backend emphasis, currently working on architecture questions, on a specific Azure stack.
Deliberately *not* taken from spec §1 and §4, which still call him "a junior fullstack
developer specialising in data and BI" — the exact premise D7 revokes. Those two paragraphs
were never back-edited after the correction, and §4 in particular reads like prose while
actually specifying the scoring prompt. Building it as written would have quietly reinstated
the corrected-away assumption in the one place it does the most damage.

**Tokens cost seconds.** Measured on this machine, intake runs at tens of tokens per second on
CPU. Every sentence in a system block is paid for on all forty scoring calls. So the system
block is short, and it is a module constant rather than an f-string: it must be byte-identical
across calls, or Ollama's prefix cache has nothing to reuse.
"""

from __future__ import annotations

# --- scoring -------------------------------------------------------------------------------

SCORE_SYSTEM = """You rate tech news for one specific reader.

The reader is a fullstack developer. His backend is Python, FastAPI, SQLModel, SQLAlchemy,
Alembic and PostgreSQL. His frontend is React 19, TypeScript, Vite, Tailwind and React Aria.
He is currently working on software architecture: service boundaries, API design, multi-tenant
data access. His infrastructure is Azure Container Apps and Functions, Key Vault, Pulumi and
Azure DevOps. He also follows which AI models were released and whether they are stronger.

He does NOT work with dbt, Databricks, Snowflake, Terraform, Kubernetes or SQL Server.

Rate how much this item helps him do his job better, from 0 to 10.
10 = directly changes how he writes or runs his own code this month.
5  = worth knowing about, not urgent.
0  = irrelevant to him, or pure marketing.

Answer with the number alone on the first line. One short reason on the second line."""

SCORE_TEMPLATE = """Title: {title}
Source: {source}
{summary}"""

# --- writing -------------------------------------------------------------------------------

WRITE_SYSTEM = """You write a short German morning briefing for one developer.

He is a fullstack developer: Python/FastAPI/PostgreSQL on the backend, React 19/TypeScript on
the frontend, currently focused on software architecture, running on Azure Container Apps with
Pulumi. He reads this in five minutes on his phone, before work.

Rules:
- German. Plain, direct, no marketing words, no exclamation marks.
- Use ONLY the items given below. Never add an item, a number, a name or a link that is not
  in the input. If you do not know something, leave it out.
- For each item: two sentences of substance, then one sentence starting with what it means for
  his own work.
- Answer with one JSON object and nothing else."""

WRITE_TEMPLATE = """Today's items:

{items}

Answer with exactly this JSON shape:
{{"judgements": [{{"item_id": "<id from above>", "headline": "<short German headline>",
"body": "<two German sentences>", "why_you": "<one German sentence: why it concerns him>"}}],
"thread": "<two German sentences connecting today's items>"}}

Write {count} judgements, one per item, in the order given."""


# --- verifying -----------------------------------------------------------------------------

# The example in the rules is deliberately NOT the 2026-09-20 failure ("slow" became "stop"):
# that case is in the labelled set, and a prompt that names its own test case measures nothing.
VERIFY_SYSTEM = """You check one line from a German news briefing against its English source.

The line may be a headline or a sentence. It may translate, simplify or shorten the source and
leave details out. Clumsy German is fine. None of that is a reason to say NO.

Answer NO only if the line says something the source does not say:
- a different action or outcome (for example "plans to release" becoming "has released"),
- a claim clearly stronger than the source's,
- the wrong company, person, place or product,
- a reason, number or detail that is not in the source.
Otherwise answer YES.

Answer with one word: YES or NO."""

# Source first, sentence last: consecutive checks against the same source then share their
# whole prefix, and Ollama's cache only has to read the new sentence.
VERIFY_TEMPLATE = """Source:
{source}

Sentence:
{sentence}

Does the source support the sentence?"""


def verify_prompt(*, source: str, sentence: str) -> str:
    return VERIFY_TEMPLATE.format(source=source.strip(), sentence=sentence.strip())


def score_prompt(*, title: str, source: str, summary: str, summary_limit: int = 320) -> str:
    """The per-item half of a scoring call. Short: it is paid for forty times per run."""
    trimmed = summary.strip()[:summary_limit]
    return SCORE_TEMPLATE.format(title=title.strip(), source=source, summary=trimmed).strip()


def write_prompt(items: str, *, count: int) -> str:
    return WRITE_TEMPLATE.format(items=items, count=count)
