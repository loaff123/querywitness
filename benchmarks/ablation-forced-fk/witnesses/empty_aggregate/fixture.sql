-- QueryWitness fixture. Inspect supplied queries before running.
PRAGMA foreign_keys=ON;
BEGIN TRANSACTION;
CREATE TABLE "t" ("x" INTEGER);
COMMIT;

-- Reference query
SELECT COALESCE(SUM(x),0) FROM t;

-- Candidate query
SELECT SUM(x) FROM t;
