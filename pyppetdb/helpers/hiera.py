# Copyright 2026 Stephan Schultchen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import string


class HieraLevelFormatter(string.Formatter):
    def get_field(self, field_name, args, kwargs):
        if field_name in kwargs:
            return kwargs[field_name], field_name
        try:
            return super().get_field(field_name, args, kwargs)
        except KeyError:
            raise KeyError(field_name)
