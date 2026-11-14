"""Reconcile derived detection associations against explicit review decisions.

Pure read-time policy: retain audit history and never manufacture a confirmation.
"""
import json


def resolve(evidence,reviews):
    rules={};physical_ignores={}
    for review in sorted(reviews,key=lambda r:(r['updated_ns'],r['id'])):
        for key in json.loads(review['source_keys']):
            rules[key]=(review['updated_ns'],key!='review:'+str(review['bib_review_id']) or review['action']=='ignored')
            if key.startswith('bike:') and review['action']=='ignored':physical_ignores[key]=review['updated_ns']
    visible=[];reconciliations=[];human_keys=set()
    for value in evidence:
        reviewed=(value.get('reviewed_ns') or 0) if value['confirmed'] else 0
        direct=rules.get(value['key']);physical=physical_ignores.get(value.get('physical_key'))
        if direct and direct[1] and reviewed<=direct[0]:continue
        if physical and reviewed<=physical:continue
        if value['confirmed']:
            if value['key'] in human_keys:
                reconciliations.append(dict(reason='duplicate_manual_association',review_key=value['key'],clip_id=value['clip_id'],bib=value['number'],ordinal=value['ordinal']))
                continue
            human_keys.add(value['key'])
            if physical or direct and direct[1] or value.get('recovered_manual') or value.get('association_reconciled'):
                reason='newer_manual_confirmation' if physical or direct and direct[1] else 'ambiguous_manual_association' if value.get('association_reconciled') else 'recovered_manual_evidence'
                reconciliations.append(dict(reason=reason,
                    review_key=value['key'],clip_id=value['clip_id'],bib=value['number'],ordinal=value['ordinal'],
                    candidate_key=value.get('physical_key') or value.get('inferred_physical_key'),reviewed_ns=reviewed,ignored_ns=physical or (direct[0] if direct else None)))
        visible.append(value)
    return dict(evidence=visible,reconciliations=reconciliations)
