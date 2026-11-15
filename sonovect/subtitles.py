"""Readable subtitle cues from actual aligned words, preserving source spelling."""
import re


def cues(evidence,max_seconds=6,max_characters=64):
    output=[]
    for channel in evidence.get('transcripts',[]):
        for sentence in channel.get('sentences',[]):
            words=sentence.get('words') or []
            source=sentence.get('text','');positions=[];cursor=0
            for word in words:
                match=re.search(re.escape(word['text'].strip()),source[cursor:],re.IGNORECASE)
                if match is None:positions=[];break
                positions.append((cursor+match.start(),cursor+match.end()));cursor+=match.end()
            if not positions:
                if source and 'begin_time' in sentence and 'end_time' in sentence:
                    output.append({'text':source,'start':sentence['begin_time'],'end':sentence['end_time']})
                continue
            current=None
            for index,word in enumerate(words):
                start=0 if index==0 else positions[index][0]
                end=positions[index+1][0] if index+1<len(words) else len(source)
                text=source[start:end]
                if current and (word['end_time']-current['start']>max_seconds*1000 or len(current['text']+text)>max_characters):
                    current['text']=current['text'].strip();output.append(current);current=None
                if current is None:current={'text':text,'start':word['begin_time'],'end':word['end_time']}
                else:current['text']+=text;current['end']=word['end_time']
            if current:current['text']=current['text'].strip();output.append(current)
    return output
