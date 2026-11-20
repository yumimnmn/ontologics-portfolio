-- C claim response (claim_response) documents on the same exact-version approval path.
-- Claim intake, containment requests, test requests/results and reproduction requirements
-- are internal development records. Nothing is sent to a customer, a test team or production.
ALTER TABLE procurement_documents DROP CONSTRAINT IF EXISTS procurement_documents_kind_check;
ALTER TABLE procurement_documents ADD CONSTRAINT procurement_documents_kind_check CHECK (kind IN
    ('QUOTE','PR','PO','SUPPLY_CONFIRMATION','RECEIPT','IQC','CANCEL','PRODUCTION','FG_RECEIPT','SHIPMENT','ARRIVAL','SCENARIO','COHORT','SUBSTITUTION',
     'CLAIM_INTAKE','CONTAINMENT','TEST_REQUEST','TEST_RESULT','REPRODUCTION'));
