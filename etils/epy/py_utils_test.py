# Copyright 2021 The etils Authors.
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

"""Tests for py_utils."""

import enum

from etils import epy


def test_str_enum():

  class MyEnum(epy.StrEnum):
    MY_OTHER_ATTR = enum.auto()
    MY_ATTR = enum.auto()

  assert MyEnum('my_attr') is MyEnum.MY_ATTR
  assert MyEnum.MY_ATTR == 'my_attr'
