"""Helpora — a payments & scholarship support agent, as a Streamlit chatbot.

Deploy on a Hugging Face **Streamlit** Space. Add your OpenRouter key as a
Space secret named OPENROUTER_KEY (Settings -> Variables and secrets).
"""

import os
import json
import sqlite3

import streamlit as st
from langchain_openai import ChatOpenAI
from langchain_core.tools import Tool
from langchain.agents import create_agent

DB_PATH = "payments.db"


# ---------------------------------------------------------------------------
# 1. Database — seeded once per container start (HF Spaces disk is ephemeral).
# ---------------------------------------------------------------------------
def seed_database():
    conn = sqlite3.connect(DB_PATH)

    conn.execute("DROP TABLE IF EXISTS payments")
    conn.execute("""
        CREATE TABLE payments (
            payment_id   TEXT,
            student_id   TEXT,
            student_name TEXT,
            amount       INTEGER,
            description  TEXT,
            date         TEXT
        )
    """)
    conn.executemany(
        "INSERT INTO payments VALUES (?,?,?,?,?,?)",
        [
            ("PAY-1001", "S-7-042", "Aditya Kumar", 15000, "Course fee - Semester 1", "2026-05-03"),
            ("PAY-1002", "S-7-042", "Aditya Kumar", 15000, "Course fee - Semester 1", "2026-05-03"),  # duplicate!
            ("PAY-1003", "S-7-118", "Meera Nair",   15000, "Course fee - Semester 1", "2026-05-04"),
            ("PAY-1004", "S-7-091", "Rohan Das",     2500, "Lab materials",           "2026-05-06"),
        ],
    )

    conn.execute("DROP TABLE IF EXISTS students")
    conn.execute("""
        CREATE TABLE students (
            student_id          TEXT,
            student_name        TEXT,
            cgpa                REAL,
            scholarship_applied INTEGER,
            invoice_term        TEXT
        )
    """)
    conn.executemany(
        "INSERT INTO students VALUES (?,?,?,?,?)",
        [
            ("S-7-043", "Riya Sharma", 9.0, 0, "Semester 3"),
            ("S-7-118", "Meera Nair",  7.2, 1, "Semester 3"),
            ("S-7-091", "Rohan Das",   5.4, 0, "Semester 3"),
        ],
    )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# 2. Tools — the agent's hands.
# ---------------------------------------------------------------------------
def lookup_payments(student_id: str) -> str:
    """Return all payment rows for a student_id, as JSON."""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT payment_id, amount, description, date FROM payments WHERE student_id = ?",
        (student_id.strip(),),
    ).fetchall()
    conn.close()
    if not rows:
        return f"No payments found for {student_id}."
    return json.dumps([
        {"payment_id": r[0], "amount": r[1], "description": r[2], "date": r[3]} for r in rows
    ])


def lookup_scholarship(student_id: str) -> str:
    """Return a student's CGPA and whether their fee waiver is on this term's invoice, as JSON."""
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT student_name, cgpa, scholarship_applied, invoice_term FROM students WHERE student_id = ?",
        (student_id.strip(),),
    ).fetchone()
    conn.close()
    if not row:
        return f"No student record found for {student_id}."
    return json.dumps({
        "student_name": row[0],
        "cgpa": row[1],
        "scholarship_applied": bool(row[2]),
        "invoice_term": row[3],
    })


def make_create_task(task_board):
    """Build a create_task tool that writes into the given task board list."""
    def create_task(summary: str) -> str:
        """Add a follow-up task to the board for a human to handle."""
        task_id = f"TASK-{len(task_board) + 1:03d}"
        task_board.append({"id": task_id, "summary": summary})
        return f"Created {task_id}: {summary}"
    return create_task


SYSTEM_PROMPT = """You are Helpora, a friendly campus payments support agent who
replies directly to students. Every reply must be warm and address the student by name.

STEP 1 — Classify the ticket as one of:
  - REFUND: the student thinks they were charged incorrectly (e.g. charged twice).
  - SCHOLARSHIP: the student is asking about a scholarship, fee waiver, or discount.

STEP 2 — Handle it.

REFUND tickets:
  1. Use lookup_payments to read the student's payments.
  2. Decide whether there is a duplicate / incorrect charge.
  3. If a refund is needed, use create_task to file it for a human (you cannot move money yourself).

SCHOLARSHIP tickets — the NIAT policy:
  - Any student with a CGPA of 6.0 or above qualifies for at least a 20% fee waiver.
  - ALWAYS use lookup_scholarship to get the student's real CGPA and whether the waiver is
    already on their invoice. NEVER guess a CGPA.
  Then:
  - Qualifies (CGPA >= 6.0) but waiver NOT applied  -> use create_task so a human applies the
    waiver to their invoice, then reassure the student it's being fixed.
  - Qualifies AND already applied                    -> warmly confirm it's already on their invoice.
  - Does NOT qualify (CGPA < 6.0)                     -> gently explain they don't meet the 6.0 CGPA
    cutoff. Be especially kind here — this is a "no" a student was hoping wouldn't come.
  - Anything unclear or borderline                    -> use create_task to hand it to a human with a
    clear reason. When in doubt, escalate rather than guess.

STEP 3 — Write a short, warm reply addressed to the student by name: what you found and
what happens next. This reply is what the student receives."""


# ---------------------------------------------------------------------------
# 3. Build the agent (cached so it survives Streamlit reruns).
# ---------------------------------------------------------------------------
@st.cache_resource
def build_agent():
    api_key = os.environ.get("OPENROUTER_KEY")
    if not api_key:
        return None, None

    seed_database()

    llm = ChatOpenAI(
        model="openai/gpt-4o-mini",
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
    )

    task_board = []
    tools = [
        Tool(
            name="lookup_payments",
            func=lookup_payments,
            description="Look up all payment records for a student. Input: the student_id, e.g. 'S-7-042'. Returns JSON.",
        ),
        Tool(
            name="create_task",
            func=make_create_task(task_board),
            description="File a follow-up task for a human. Input: a one-line summary of what needs to be done.",
        ),
        Tool(
            name="lookup_scholarship",
            func=lookup_scholarship,
            description=(
                "Look up a student's CGPA and whether their scholarship/fee-waiver is already on "
                "this term's invoice. Input: the student_id, e.g. 'S-7-043'. Returns JSON. "
                "Use this for scholarship / fee-waiver / discount questions."
            ),
        ),
    ]

    agent = create_agent(model=llm, tools=tools, system_prompt=SYSTEM_PROMPT)
    return agent, task_board


# ---------------------------------------------------------------------------
# 4. Streamlit UI.
# ---------------------------------------------------------------------------
st.set_page_config(page_title="Helpora 🤖", page_icon="🤖")
st.title("Helpora 🤖")
st.caption("A payments & scholarship support agent · Agentic AI Workshop · NIAT")

agent, task_board = build_agent()

if agent is None:
    st.error(
        "OPENROUTER_KEY not set. Add it under **Settings → Variables and secrets** "
        "on this Space, then restart."
    )
    st.stop()

with st.sidebar:
    st.header("Try these tickets")
    st.markdown(
        "- **Aditya (refund):** `I think I was charged twice for my course fee. "
        "My student ID is S-7-042.`\n"
        "- **Riya (scholarship, unapplied):** `My scholarship hasn't been applied "
        "to my invoice. My student ID is S-7-043.`\n"
        "- **Rohan (below cutoff):** `Can I get the scholarship fee waiver? "
        "My student ID is S-7-091.`\n"
        "- **Meera (already applied):** `Is my scholarship on my invoice? "
        "My student ID is S-7-118.`"
    )
    if st.button("Clear chat"):
        st.session_state.messages = []
        st.rerun()

if "messages" not in st.session_state:
    st.session_state.messages = []

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

if prompt := st.chat_input("Describe your payment or scholarship issue…"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Helpora is looking into it…"):
            result = agent.invoke({"messages": [("user", prompt)]})
            reply = result["messages"][-1].content
        st.markdown(reply)

    st.session_state.messages.append({"role": "assistant", "content": reply})

    if task_board:
        with st.sidebar:
            st.header("Task board")
            for t in task_board:
                st.markdown(f"**{t['id']}** — {t['summary']}")
