-- QueryWitness fixture. Inspect supplied queries before running.
PRAGMA foreign_keys=ON;
BEGIN TRANSACTION;
CREATE TABLE "t" ("g" TEXT NOT NULL,"x" INTEGER NOT NULL);
INSERT INTO "t" VALUES('A',0);
INSERT INTO "t" VALUES('B',6);
INSERT INTO "t" VALUES('B',0);
COMMIT;

-- Reference query
SELECT AVG(x) FROM t;

-- Candidate query
SELECT AVG(a) FROM (SELECT g,AVG(x) AS a FROM t GROUP BY g);
