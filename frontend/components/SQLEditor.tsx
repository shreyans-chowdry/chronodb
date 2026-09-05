"use client";

import { useState } from "react";
import { createCommit } from "@/lib/api";

interface SQLEditorProps {
  branchName: string;
  onSuccess: () => void;
}

export default function SQLEditor({ branchName, onSuccess }: SQLEditorProps) {
  const [sql, setSql] = useState("");
  const [isRunning, setIsRunning] = useState(false);
  const [output, setOutput] = useState<{ type: "success" | "error"; msg: string } | null>(null);

  const parseAndExecuteSQL = async () => {
    if (!sql.trim()) return;
    setIsRunning(true);
    setOutput(null);

    try {
      // 1. Remove comments and normalize newlines
      const cleanSql = sql
        .replace(/--.*$/gm, "")
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/\n/g, " ")
        .trim();

      // 2. Split by semicolon
      const statements = cleanSql.split(";").map((s) => s.trim()).filter(Boolean);
      
      const tables: Record<string, string[]> = {};
      const changes: any[] = [];

      for (const stmt of statements) {
        // MATCH: CREATE TABLE table_name (col1, col2, col3)
        const createMatch = stmt.match(/CREATE\s+TABLE\s+([a-zA-Z0-9_]+)\s*\((.*?)\)/i);
        if (createMatch) {
          const tableName = createMatch[1];
          const cols = createMatch[2].split(",").map(c => c.trim().split(" ")[0]); // extract names, ignore types if any
          tables[tableName] = cols;
          continue;
        }

        // MATCH: INSERT INTO table_name VALUES ('val1', 'val2', 'val3')
        const insertMatch = stmt.match(/INSERT\s+INTO\s+([a-zA-Z0-9_]+)\s*(?:\([^)]+\))?\s*VALUES\s*\((.*?)\)/i);
        if (insertMatch) {
          const tableName = insertMatch[1];
          const rawValues = insertMatch[2];
          
          if (!tables[tableName]) {
            throw new Error(`Table '${tableName}' has not been created in this script. Run CREATE TABLE first.`);
          }
          
          const cols = tables[tableName];
          
          // Parse values (simple split by comma, respecting basic quotes)
          // A real parser would be a state machine. This handles 'a', 'b', 123
          const values = rawValues.match(/('[^']*'|"[^"]*"|[^,]+)/g)?.map(v => v.trim().replace(/^['"]|['"]$/g, "")) || [];

          if (values.length !== cols.length) {
            throw new Error(`INSERT into '${tableName}' failed: provided ${values.length} values but expected ${cols.length} columns.`);
          }

          // The first column is mapped to ChronoDB's internal row_id
          const rowId = values[0];
          const data: Record<string, string> = {};
          
          for (let i = 1; i < cols.length; i++) {
            data[cols[i]] = values[i];
          }

          changes.push({
            action: "insert",
            table_name: tableName,
            row_id: rowId,
            data: data
          });
          continue;
        }
        
        // MATCH: DELETE FROM table_name WHERE primary_key = 'val'
        const deleteMatch = stmt.match(/DELETE\s+FROM\s+([a-zA-Z0-9_]+)\s+WHERE\s+[a-zA-Z0-9_]+\s*=\s*('[^']*'|"[^"]*"|[^ ]+)/i);
        if (deleteMatch) {
          const tableName = deleteMatch[1];
          const rowId = deleteMatch[2].replace(/^['"]|['"]$/g, "");
          
          changes.push({
            action: "delete",
            table_name: tableName,
            row_id: rowId,
            data: {}
          });
          continue;
        }

        // MATCH: UPDATE table_name SET col1='val1', col2='val2' WHERE primary_key = 'val'
        const updateMatch = stmt.match(/UPDATE\s+([a-zA-Z0-9_]+)\s+SET\s+(.+?)\s+WHERE\s+[a-zA-Z0-9_]+\s*=\s*('[^']*'|"[^"]*"|[^ ]+)/i);
        if (updateMatch) {
          const tableName = updateMatch[1];
          const setClause = updateMatch[2];
          const rowId = updateMatch[3].replace(/^['"]|['"]$/g, "");
          
          const data: Record<string, string> = {};
          // Split by comma, then by equals (simple parsing)
          const assignments = setClause.split(",");
          for (const assign of assignments) {
            const parts = assign.split("=");
            if (parts.length >= 2) {
              const key = parts[0].trim();
              const val = parts.slice(1).join("=").trim().replace(/^['"]|['"]$/g, "");
              data[key] = val;
            }
          }

          changes.push({
            action: "update",
            table_name: tableName,
            row_id: rowId,
            data: data
          });
          continue;
        }

        throw new Error(`Unsupported SQL statement: "${stmt.substring(0, 50)}..."`);
      }

      if (changes.length === 0) {
        throw new Error("No valid INSERT statements found to commit.");
      }

      // Execute Commit
      await createCommit(
        branchName,
        `SQL Script Execution (${changes.length} ops)`,
        "SQL Runner",
        changes
      );

      setOutput({ type: "success", msg: `Successfully executed script! Applied ${changes.length} mutations.` });
      setSql("");
      onSuccess();

    } catch (err) {
      setOutput({ type: "error", msg: err instanceof Error ? err.message : "Failed to parse/execute SQL." });
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-xl border border-zinc-200 bg-white shadow-xs">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-200 px-5 py-3 bg-zinc-50/50">
        <h2 className="text-sm font-semibold text-zinc-900 flex items-center gap-2">
          <svg className="h-4 w-4 text-violet-600" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M17.25 6.75 22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3-4.5 16.5" />
          </svg>
          SQL Runner
        </h2>
        <button
          onClick={parseAndExecuteSQL}
          disabled={isRunning || !sql.trim()}
          className="flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-medium text-white transition-all hover:bg-violet-500 disabled:opacity-50 active:scale-95 shadow-sm"
        >
          {isRunning ? (
            <div className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-white border-t-transparent" />
          ) : (
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M5.25 5.653c0-.856.917-1.398 1.667-.986l11.54 6.347a1.125 1.125 0 0 1 0 1.972l-11.54 6.347a1.125 1.125 0 0 1-1.667-.986V5.653Z" />
            </svg>
          )}
          Run Script
        </button>
      </div>
      
      <div className="flex-1 flex flex-col p-4 bg-zinc-900 relative">
        <div className="mb-4 rounded-md bg-blue-50/10 p-4 border border-blue-500/20">
          <div className="flex">
            <div className="shrink-0">
              <svg className="h-5 w-5 text-blue-400" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a.75.75 0 000 1.5h.253a.25.25 0 01.244.304l-.459 2.066A1.75 1.75 0 0010.747 15H11a.75.75 0 000-1.5h-.253a.25.25 0 01-.244-.304l.459-2.066A1.75 1.75 0 009.253 9H9z" clipRule="evenodd" />
              </svg>
            </div>
            <div className="ml-3 flex-1 md:flex md:justify-between">
              <p className="text-sm text-blue-300">
                <strong>Note:</strong> ChronoDB is a versioned NoSQL datastore, not a relational SQL database. This runner acts as a translator to JSON commits.
                <br/>Supported commands: <code className="text-xs bg-blue-900/50 px-1 py-0.5 rounded">CREATE TABLE</code>, <code className="text-xs bg-blue-900/50 px-1 py-0.5 rounded">INSERT INTO</code>, <code className="text-xs bg-blue-900/50 px-1 py-0.5 rounded">UPDATE...WHERE id='x'</code>, and <code className="text-xs bg-blue-900/50 px-1 py-0.5 rounded">DELETE FROM...WHERE id='x'</code>.
              </p>
            </div>
          </div>
        </div>

        <textarea
          value={sql}
          onChange={(e) => setSql(e.target.value)}
          placeholder="CREATE TABLE users (id, name, age);&#10;INSERT INTO users VALUES ('user_1', 'Alice', '25');&#10;UPDATE users SET age='26' WHERE id='user_1';&#10;DELETE FROM users WHERE id='user_1';"
          className="flex-1 w-full resize-none bg-transparent text-sm font-mono text-zinc-100 placeholder-zinc-600 outline-none"
          spellCheck={false}
        />
      </div>

      {output && (
        <div className={`px-5 py-3 text-sm font-mono border-t ${
          output.type === "success" 
            ? "bg-green-50/50 border-green-100 text-green-700" 
            : "bg-red-50/50 border-red-100 text-red-600"
        }`}>
          {output.msg}
        </div>
      )}
    </div>
  );
}
