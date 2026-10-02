"""Constraint-preserving row reduction with explicit finite-work guarantees."""
from copy import deepcopy
import math
import time
from .schema import Schema, SchemaError
from .engine import execute, ExecutionLimits
from .compare import compare_results

class BudgetExceeded(Exception):pass

def minimize(schema:Schema,instance:dict,reference:str,candidate:str,policy='bag',max_checks=500,seconds=30.0,limits:ExecutionLimits|None=None,*,deletion_mode='row')->dict:
    if deletion_mode not in ('row','fk-closure'):raise ValueError('Unknown deletion mode')
    if deletion_mode=='fk-closure':
        from .fk_closure import minimize_fk_closure
        return minimize_fk_closure(schema,instance,reference,candidate,policy,max_checks,seconds,limits)
    if type(max_checks) is not int or not 1<=max_checks<=10000:raise ValueError('Invalid reduction check budget')
    if not isinstance(seconds,(float,int)) or not math.isfinite(seconds) or not 0<seconds<=300:raise ValueError('Invalid reduction time budget')
    schema.validate_instance(instance);current=deepcopy(instance);checks=0;start=time.monotonic();inconclusive=0
    def remains(data):
        nonlocal checks,inconclusive
        try:schema.validate_instance(data)
        except SchemaError:return False
        if checks>=max_checks or time.monotonic()-start>=seconds:raise BudgetExceeded()
        checks+=1
        result=compare_results(execute(schema,data,reference,limits,policy=policy),execute(schema,data,candidate,limits,policy=policy),policy)
        if result['status']=='inconclusive':inconclusive+=1
        return result['status']=='mismatch'
    initial_size=sum(map(len,current.values()));status='minimized';minimal=False
    try:
        if not remains(current):return {'status':'not_a_witness','instance':current,'checks':checks,'row_1_minimal':False,'inconclusive_checks':inconclusive}
        # Complement chunk deletion improves speed, retaining every relational constraint.
        for name in sorted(current):
            n=2
            while current[name]:
                rows=current[name];width=max(1,math.ceil(len(rows)/n));changed=False
                for begin in range(0,len(rows),width):
                    proposal=deepcopy(current);proposal[name]=rows[:begin]+rows[begin+width:]
                    if remains(proposal):current=proposal;n=max(2,n-1);changed=True;break
                if changed:continue
                if n>=len(rows):break
                n=min(len(rows),n*2)
        # Global single-row pass is necessary after dependencies changed in later tables.
        changed=True
        while changed:
            changed=False
            for name in sorted(current):
                for index in range(len(current[name])):
                    proposal=deepcopy(current);del proposal[name][index]
                    if remains(proposal):current=proposal;changed=True;break
                if changed:break
        minimal=inconclusive==0
        if not minimal:status='inconclusive_reduction'
    except BudgetExceeded:status='budget_exhausted'
    return {'status':status,'instance':current,'checks':checks,'initial_rows':initial_size,'final_rows':sum(map(len,current.values())),'row_1_minimal':minimal,'inconclusive_checks':inconclusive,'guarantee':'No schema-valid single-row deletion preserves a successful result mismatch' if minimal else 'Best preserved witness within reduction budget; minimality not established'}
