"""Attach diarization after ASR; preserve original text and ambiguous overlap."""
from bisect import bisect_left, bisect_right

def attribution(start, end, turns):
    durations={}
    for turn in turns:
        overlap=max(0,min(end,turn['end_ms'])-max(start,turn['start_ms']))
        if overlap:
            key=turn['speaker'];durations[key]=durations.get(key,0)+overlap
    ranked=sorted(durations,key=lambda key:durations[key],reverse=True)
    if not ranked:return None,False
    # A second voice covering a substantial part of this word is ambiguous.
    ambiguous=len(ranked)>1 and durations[ranked[1]]>=max(1,(end-start)*0.25)
    active=[t for t in turns if min(end,t['end_ms'])>max(start,t['start_ms'])]
    overlap=any(a['speaker']!=b['speaker'] and
                min(end,a['end_ms'],b['end_ms'])>max(start,a['start_ms'],b['start_ms'])
                for i,a in enumerate(active) for b in active[i+1:])
    return (None if ambiguous else ranked[0]),overlap


def align_speakers(segments,turns):
    ordered=sorted(turns,key=lambda t:t['start_ms'])
    starts=[t['start_ms'] for t in ordered]
    ends=[]
    for turn in ordered:
        ends.append(max(turn['end_ms'],ends[-1] if ends else 0))
    def assign(start,end):
        # Limit each word's search to potentially intersecting turns.
        return attribution(start,end,ordered[bisect_right(ends,start):bisect_left(starts,end)])
    result=[]
    for segment in segments:
        text=str(segment.get('text') or '')
        words=segment.get('words') or []
        positions=[];cursor=0
        for word in words:
            value=str(word.get('text') or '').strip()
            found=text.find(value,cursor) if value else -1
            if found<0:positions=[];break
            positions.append(found);cursor=found+len(value)
        if not positions:
            # Without exact text/word correspondence, don't destroy punctuation
            # or invent precise speaker changes within the segment.
            speaker,overlap=assign(segment['start_ms'],segment['end_ms'])
            result.append({**segment,'speaker':speaker,'overlap':overlap,'speaker_alignment':'segment-only'})
            continue
        groups=[]
        for index,word in enumerate(words):
            speaker,overlap=assign(word['start_ms'],word['end_ms'])
            key=(speaker,overlap)
            if not groups or groups[-1]['key']!=key:groups.append(dict(key=key,start=index,end=index+1))
            else:groups[-1]['end']=index+1
        for group in groups:
            a,b=group['start'],group['end']
            start=0 if a==0 else positions[a]
            end=len(text) if b==len(words) else positions[b]
            result.append({**segment,'text':text[start:end],'raw_text':text[start:end],
                'words':words[a:b],'start_ms':words[a]['start_ms'],'end_ms':words[b-1]['end_ms'],
                'speaker':group['key'][0],'overlap':group['key'][1],'speaker_alignment':'word'})
        if ''.join(item['text'] for item in result[-len(groups):])!=text:
            raise RuntimeError('speaker_alignment_text_coverage_mismatch')
    return result
