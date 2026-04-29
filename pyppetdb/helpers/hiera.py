import string


class HieraLevelFormatter(string.Formatter):
    def get_field(self, field_name, args, kwargs):
        if field_name in kwargs:
            return kwargs[field_name], field_name
        try:
            return super().get_field(field_name, args, kwargs)
        except KeyError:
            raise KeyError(field_name)
