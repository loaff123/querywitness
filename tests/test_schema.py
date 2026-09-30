import unittest
from querywitness.schema import Schema, SchemaError

DEFINITION = {'tables': [
 {'name': 'people', 'columns': [{'name': 'id', 'type': 'INTEGER', 'nullable': False}, {'name': 'name', 'type': 'TEXT'}], 'primary_key': ['id']},
 {'name': 'orders', 'columns': [{'name': 'id', 'type': 'INTEGER', 'nullable': False}, {'name': 'person', 'type': 'INTEGER'}, {'name': 'amount', 'type': 'INTEGER', 'nullable': False}], 'primary_key': ['id'], 'foreign_keys': [{'columns': ['person'], 'references': {'table': 'people', 'columns': ['id']}}]}
]}
class SchemaTests(unittest.TestCase):
 def test_valid_null_foreign_key(self):
  schema=Schema.from_dict(DEFINITION)
  schema.validate_instance({'people': [[1,'A']], 'orders': [[1,1,100],[2,None,-10]]})
 def test_missing_foreign_key_rejected(self):
  schema=Schema.from_dict(DEFINITION)
  with self.assertRaises(SchemaError): schema.validate_instance({'people': [],'orders': [[1,2,100]]})
 def test_duplicate_primary_key_rejected(self):
  schema=Schema.from_dict(DEFINITION)
  with self.assertRaises(SchemaError): schema.validate_instance({'people': [[1,'A'],[1,'B']], 'orders': []})
 def test_boolean_not_integer(self):
  with self.assertRaises(SchemaError): Schema.from_dict(DEFINITION).validate_instance({'people': [[True,'A']], 'orders': []})
 def test_nullable_defaults_explicit(self):
  Schema.from_dict(DEFINITION).validate_instance({'people': [[1,None]],'orders': []})
 def test_unknown_field_rejected(self):
  with self.assertRaises(SchemaError): Schema.from_dict({'tables':DEFINITION['tables'],'sql':'DROP TABLE x'})
 def test_unknown_table_rejected(self):
  with self.assertRaises(SchemaError): Schema.from_dict(DEFINITION).validate_instance({'people': [],'orders': [],'extra': []})
 def test_identifiers_case_insensitive_collision(self):
  with self.assertRaises(SchemaError): Schema.from_dict({'tables':[{'name':'x','columns':[{'name':'a','type':'TEXT'},{'name':'A','type':'TEXT'}]}]})
 def test_huge_real_integer_is_clean_error(self):
  s=Schema.from_dict({"tables":[{"name":"t","columns":[{"name":"a","type":"REAL"}]}]})
  with self.assertRaises(SchemaError):s.validate_instance({"t":[[10**400]]})
 def test_domain_enforced(self):
  s=Schema.from_dict({'tables':[{'name':'t','columns':[{'name':'a','type':'INTEGER','domain':[1,2]}]}]})
  s.validate_instance({'t':[[1],[None]]})
  with self.assertRaises(SchemaError):s.validate_instance({'t':[[3]]})
if __name__=='__main__': unittest.main()
