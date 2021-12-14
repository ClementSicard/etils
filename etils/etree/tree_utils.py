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

"""Tree API."""

import concurrent.futures
import functools
from typing import Any, Callable, Iterable, Iterator, Optional, TypeVar

from etils.etree import backend as backend_lib
from etils.etree.typing import Tree
# TODO(epot): Wrap tqdm in a tqdm util
import tqdm

_T = Any  # TODO(pytype): Replace by `TypeVar`
_Tin = Any  # Could make this TypeVar if typing support variadic
_Tout = TypeVar('_Tout')


class TreeAPI:
  """Tree API, using either `jax.tree_utils`, `tf.nest` or `tree` backend."""

  def __init__(self, backend: backend_lib.Backend):
    self.backend = backend

  def parallel_map(
      self,
      map_fn: Callable[..., _Tout],  # Callable[[_Tin0, _Tin1,...], Tout]
      *trees: Tree[_Tin],  # _Tin0, _Tin1,...
      num_threads: Optional[int] = None,
      progress_bar: bool = False,
  ) -> Tree[_Tout]:
    """Same as `tree.map_structure` but apply `map_fn` in parallel.

    Args:
      map_fn: Worker function
      *trees: Nested input to pass to the `map_fn`
      num_threads: Number of workers (default to CPU count * 5)
      progress_bar: If True, display a progression bar.

    Returns:
      The nested structure after `map_fn` has been applied.
    """
    # TODO(epot): Allow nesting `parallel_map` while keeping max num threads
    # constant. How to avoid dead locks ?

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=num_threads) as executor:
      launch_worker = functools.partial(executor.submit, map_fn)
      futures = self.backend.map(launch_worker, *trees)

      leaves, _ = self.backend.flatten(futures)

      itr = concurrent.futures.as_completed(leaves)
      if progress_bar:
        itr = tqdm.tqdm(itr, total=len(leaves))

      for f in itr:  # Propagate exception to main thread.
        if f.exception():
          raise f.exception()

    return self.backend.map(lambda f: f.result(), futures)

  def unzip(self, tree: Tree[Iterable[_T]]) -> Iterator[Tree[_T]]:
    """Unpack a tree of iterable.

    This is the reverse operation of `tree.map_structure(zip, *trees)`

    Example:

    ```python
    etree.unzip({'a': np.array([1, 2, 3])}) == [{'a': 1}, {'a': 2}, {'a': 3}]
    ```

    Args:
      tree: The tree to unzip

    Yields:
      Trees of same structure than the input, but with individual elements.
    """
    leaves, treedef = self.backend.flatten(tree)
    for leaf_elems in zip(*leaves):  # TODO(py3.10): check=True
      yield self.backend.unflatten(treedef, leaf_elems)
