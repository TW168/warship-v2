---
name: anti-hallucination
description: Strict protocols to prevent the AI from inventing logistics data or MySQL trends.
---

# Anti-Hallucination Skill

## 1. Data Grounding
- **Zero Speculation:** You must only use data found in the MySQL database or the `raw_data/` directory.
- **Mandatory Citations:** Every number or trend must be tagged with its source (e.g., `[Source: MySQL]` or `[Source: lmi_scores.csv]`).

## 2. Verification Logic
- **Path Check:** Before proposing a query, verify the file exists in the current project tree.
- **Schema Check:** Cross-reference `schemas/` and the MySQL structure before generating SQL.
- **Missing Data:** If a data point is missing, the answer must be "Data unavailable." Do not guess.

## 3. SQL Integrity
- Generate `SELECT` queries only. 
- Math must happen in MySQL, not in the LLM's head.
