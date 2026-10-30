# Agentic Data Analyst

Ask about **speedruns by humans and AI agents** in five retro games: best times, AI progress over time, per-level splits, resets and DNFs.

**How an answer is made:** the Analyst agent looks up the tables it needs, writes a SQL query, a second **SQL Reviewer** agent checks it, and only then **DuckDB** runs it. Open the *Analyst* step under an answer to see the flow and the SQL. Ask for a table or a chart when you want one.

- Claude never reads the tables directly. Every number in an answer comes from the rows of the SQL in its details.
- Queries are read-only and sandboxed: the data cannot be changed, and no other files or the network can be reached.
- Each answer and each chat has a cost limit; the cost is shown under every answer.
- The data is synthetic: the games, runners and AI agents are invented.
