-- QueryWitness fixture. Inspect supplied queries before running.
PRAGMA foreign_keys=ON;
BEGIN TRANSACTION;
CREATE TABLE "c" ("pid" INTEGER,"amount" INTEGER,FOREIGN KEY ("pid") REFERENCES "p"("id") DEFERRABLE INITIALLY DEFERRED);
CREATE TABLE "p" ("id" INTEGER NOT NULL,PRIMARY KEY ("id"));
INSERT INTO "p" VALUES(1);
COMMIT;

-- Reference query
SELECT p.id,c.amount FROM p LEFT JOIN c ON c.pid=p.id AND c.amount>0;

-- Candidate query
SELECT p.id,c.amount FROM p LEFT JOIN c ON c.pid=p.id WHERE c.amount>0;
