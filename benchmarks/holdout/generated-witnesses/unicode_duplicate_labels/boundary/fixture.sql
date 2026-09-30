-- QueryWitness fixture. Inspect supplied queries before running.
PRAGMA foreign_keys=ON;
BEGIN TRANSACTION;
CREATE TABLE "label_event" ("label" TEXT NOT NULL,"score" INTEGER NOT NULL);
INSERT INTO "label_event" VALUES('',0);
INSERT INTO "label_event" VALUES('',0);
COMMIT;

-- Reference query
SELECT label,COUNT(*) FROM label_event GROUP BY label;

-- Candidate query
SELECT label,COUNT(DISTINCT score) FROM label_event GROUP BY label;
