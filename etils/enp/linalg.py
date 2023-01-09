# Copyright 2022 The etils Authors.
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

"""`linalg` compat module for interoperability between tf, jax, numpy."""

from __future__ import annotations

from typing import Optional

from etils.enp import numpy_utils
from etils.enp.typing import Array, FloatArray  # pylint: disable=g-multiple-import

lazy = numpy_utils.lazy


# ================ Utils (not present in numpy) ================


def normalize(x: FloatArray['*d'], axis: int = -1) -> FloatArray['*d']:
  """Normalize the vector to the unit norm."""
  return x / norm(x, axis=axis, keepdims=True)


# ================ Compat utils (between TF/Jax/np) ================


def norm(
    x: FloatArray['*d'],
    axis: Optional[int] = None,
    keepdims: bool = False,
) -> FloatArray['*d']:
  """Like `np.linalg.norm` but auto-support jnp, tnp, np."""
  if lazy.is_tf(x):  # TODO(b/219427516): tnp.linalg.norm missing
    return lazy.tf.norm(x, axis=axis, keepdims=keepdims)
  xnp = lazy.get_xnp(x)
  return xnp.linalg.norm(x, axis=axis, keepdims=keepdims)


def inv(x: FloatArray['*d']) -> FloatArray['*d']:
  """Like `np.linalg.inv` but auto-support jnp, tnp, np."""
  return _tf_or_xnp(x).linalg.inv(x)


def det(x: FloatArray['*d m m']) -> FloatArray['*d']:
  """Like `np.linalg.det` but auto-support jnp, tnp, np."""
  return _tf_or_xnp(x).linalg.det(x)


def _tf_or_xnp(x: Array['*d']):
  xnp = lazy.get_xnp(x)
  if lazy.has_tf and xnp is lazy.tnp:
    return lazy.tf
  else:
    return xnp
