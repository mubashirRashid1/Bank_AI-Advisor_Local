from db import get_chroma_collection, semantic_search_chroma
print('Total in ChromaDB:', get_chroma_collection().count())
r = semantic_search_chroma('Canadian REIT rates', limit=3)
print('Search results:', len(r))
for x in r: print(' -', x.get('TITLE','')[:60])
