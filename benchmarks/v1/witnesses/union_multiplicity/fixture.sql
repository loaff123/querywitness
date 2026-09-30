-- QueryWitness fixture. Inspect supplied queries before running.
PRAGMA foreign_keys=ON;
BEGIN TRANSACTION;
CREATE TABLE "t" ("x" INTEGER NOT NULL);
INSERT INTO "t" VALUES(20);
INSERT INTO "t" VALUES(20);
COMMIT;

-- Reference query
SELECT x FROM t WHERE x<=1 UNION ALL SELECT x FROM t WHERE x>1;

-- Candidate query
SELECT x FROM t WHERE x<=1 UNION SELECT x FROM t WHERE x>1;
