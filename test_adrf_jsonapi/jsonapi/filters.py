from .helpers import getattr


# TODO: test all the filter lookups
class JSONAPIFilter:
    def __init__(self, queryset, request):
        self.queryset = queryset
        self.request = request
        self.params = {}
    
    async def filter_queryset(self):
        return self.queryset.filter(**await self._get_params())
        
    async def _get_params(self):
        for key, val in self.request.query_params.items():
            if not key.startswith('filter['):
                continue
            key = key.split('[')[-1].replace(']', '')
            if '__' in key:
                split_key = key.split('__')
                key, lookup = split_key[0], '__' + split_key[1]
            else:
                lookup = '__in'
            try:
                is_relation = await getattr(self.queryset.model, key, None)
            except AttributeError:
                continue
            is_relation = bool(is_relation.field.remote_field)
            key = key + '__id' + lookup if is_relation else key + lookup
            if ',' not in val and lookup != '__in' and val.isnumeric():
                val = int(val)
            elif lookup == '__range':
                split = val.split(',')
                val = [split[0], split[1]]
            else:
                val = val.split(',')
            if type(val) == list and val.pop(0, None):
                self.params.update({key: val})
            else:
                self.params.update({key: []})
        return self.params
