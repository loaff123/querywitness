-- QueryWitness fixture. Inspect supplied queries before running.
PRAGMA foreign_keys=ON;
BEGIN TRANSACTION;
CREATE TABLE "label" ("text" TEXT);
INSERT INTO "label" VALUES('mañana/雪/🙂/é');
COMMIT;

-- Reference query
SELECT text FROM label WHERE text = 'mañana/雪/🙂/é';

-- Candidate query
SELECT text FROM label WHERE text = 'mañana/雪/🙂/é';
