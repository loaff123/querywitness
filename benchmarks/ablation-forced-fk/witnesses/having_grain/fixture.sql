-- QueryWitness fixture. Inspect supplied queries before running.
PRAGMA foreign_keys=ON;
BEGIN TRANSACTION;
CREATE TABLE "t" ("g" TEXT NOT NULL,"x" INTEGER NOT NULL);
INSERT INTO "t" VALUES('B',10);
INSERT INTO "t" VALUES('B',20);
COMMIT;

-- Reference query
SELECT g,SUM(x) FROM t GROUP BY g HAVING SUM(x)>10;

-- Candidate query
SELECT g,SUM(x) FROM t WHERE x>10 GROUP BY g;
