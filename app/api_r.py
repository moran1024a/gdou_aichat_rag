from django.http import JsonResponse

class APIResponse(JsonResponse):
    def __init__(self, code=0, msg='', data=None, status=200, headers=None, content_type='application/json;charset=utf-8', **kwargs):
        dic = {'code': code, 'msg': msg}
        if data is not None:
            dic['data'] = data

        dic.update(kwargs)

        super().__init__(
            data=dic,
            status=status,
            headers=headers,
            content_type=content_type
        )