# Copyright 2024 The etils Authors.
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

"""Cell auto-reload."""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import importlib
import inspect
import re
import sys
import types
from typing import Iterator
from unittest import mock

from etils import epath
from etils.ecolab import adhoc_imports
from etils.ecolab import colab_utils
from etils.ecolab import ip_utils
from etils.epy.adhoc_utils import module_utils
import IPython


@dataclasses.dataclass(frozen=True)
class _ModuleInfo:
  name: str
  instance: types.ModuleType


def _create_module_graph(nodes: set[str]) -> dict[str, set[str]]:
  graph = {}

  for source in nodes:
    deps = set()
    for val in sys.modules[source].__dict__.values():
      if inspect.ismodule(val) and val.__name__ in nodes:
        deps.add(val.__name__)
    graph[source] = deps

  return graph


class _ModuleSearch:
  """Graph of module dependencies that can be queried."""

  def __init__(self, targets: set[str], graph: dict[str, set[str]]):
    self._graph = graph
    self._cache: dict[str, bool] = {}
    self._targets = targets

  def _reaches_targets(self, source: str) -> bool:
    """Check if a module references other modules directly or indirectly."""
    queue = [source]
    visited = set(queue)

    while queue:
      m = queue.pop(0)

      if (reaches := self._cache.get(m)) is not None:
        if reaches:
          # If m is known to reach target -> source reaches targets
          return True
        else:
          # Otherwise, no need to search the neighbours of this node either.
          continue

      if m in self._targets:
        return True

      for neighbour in self._graph.get(m, set()):
        if neighbour not in visited:
          visited.add(neighbour)
          queue.append(neighbour)

    return False

  def reaches_targets(self, source: str) -> bool:
    """Check if a module references other modules directly or indirectly."""
    ret = self._reaches_targets(source)
    self._cache[source] = ret
    return ret


class ModuleReloader:
  """Module reloader."""

  def __init__(self, **adhoc_kwargs):
    self.adhoc_kwargs = adhoc_kwargs
    self._last_updates: dict[str, int | None] = {}
    self._globals_to_update: dict[str, _ModuleInfo] = {}

  @functools.cached_property
  def reload(self) -> tuple[str, ...]:
    return tuple(self.adhoc_kwargs['reload'])

  def print(self, *txt) -> bool:
    if self.verbose:
      print(*txt)

  @property
  def verbose(self) -> bool:
    return self.adhoc_kwargs['verbose']

  def register(self) -> None:
    if not self.reload:
      raise ValueError('`cell_autoreload=True` require to set `reload=`')

    # Keep a value for each module. If a file is updated, trigger a reload.
    for module in module_utils.get_module_names(self.reload):
      self._last_updates[module] = _get_last_module_update(module)

    # Currently, only a single auto-reload can be set at the time.
    # Probably a good idea as it's unclear how to differentiate between
    # registering 2 cell_autoreload and overwriting cell_autoreload params.
    ip_utils.register_once(
        'pre_run_cell',
        # Cannot use `self.method` because bound methods do not support
        # set attribute.
        functools.partial(type(self)._pre_run_cell_maybe_reload, self),
        'is_cell_auto_reload',
    )

  @contextlib.contextmanager
  def track_globals(self) -> Iterator[None]:
    """Record the imported modules."""
    # TODO(epot): Could likely be simplified or deleted entirely. When
    # auto_reload only uses `reload_mode='inplace'`
    # Or at minima, should be moved in `_pre_run_cell_maybe_reload`

    ip = IPython.get_ipython()
    yield
    # Do not try to catch error.
    new_globals = dict(ip.kernel.shell.user_ns)

    # Filter only the modules
    # This means that `from module import function` or `from module import *`
    # won't be reloaded
    for name, value in new_globals.items():
      # We look at all globals, not just the ones defined inside the
      # contextmanager. Indeed, it's not trivial to detect when a module is
      # re-imported, like:
      #
      # import module
      # with ecolab.adhoc():
      #   import module  # < globals() not modified, difficult to detect
      #
      # The solution would be to mock `__import__` to capture all statements
      # but over-engineered for now.
      if not isinstance(value, types.ModuleType):
        continue  # The object is not a module
      if not value.__dict__.get('__name__', '').startswith(self.reload):
        continue  # The module won't be reloaded
      if re.fullmatch(r'_+(\d+)?', name):
        continue  # Internal IPython variables (`_`, `__`, `_12`)
      self.print(f'Registering {name} for autoreload ({value.__name__})')
      # Should update the global
      self._globals_to_update[name] = _ModuleInfo(
          name=value.__name__, instance=value
      )

  def _pre_run_cell_maybe_reload(
      self,
      *args,
  ) -> None:
    """Check if workspace is modified, then eventually reload modules."""
    del args  # Future version of IPython will have a `info` arg

    # If any of the modules has been updated, trigger a reload

    # Find which modules are dirty.
    dirty_modules: set[str] = set()
    for module in module_utils.get_module_names(self.reload):
      prev_mtime = self._last_updates.get(module)
      new_mtime = _get_last_module_update(module)
      if prev_mtime is None or (
          new_mtime is not None and new_mtime > prev_mtime
      ):
        dirty_modules.add(module)
      self._last_updates[module] = new_mtime

    if not dirty_modules:
      return

    # Get set of all modules we could potentially reload.
    reload_set = set(module_utils.get_module_names(self.reload))
    graph = _create_module_graph(reload_set)
    search = _ModuleSearch(dirty_modules, graph)

    # Narrow it down to modules that are dirty or reference a dirty module.
    modules_to_update = [
        mod for mod in reload_set if search.reaches_targets(mod)
    ]

    with contextlib.ExitStack() as stack:
      if self.verbose:
        # Hide the logs in a collapsible section (less boilerplate)
        mod_plural = 'module' if len(modules_to_update) == 1 else 'modules'
        stack.enter_context(
            colab_utils.collapse(
                f'{len(modules_to_update)} {mod_plural} reloaded'
            )
        )
        stack.enter_context(contextlib.redirect_stderr(sys.stdout))

      # Only reload exactly the modules we know are dirty. reload_recursive
      # is an undocumented flag in adhoc for now.
      adhoc_kwargs = self.adhoc_kwargs | {
          'reload': modules_to_update,
          'reload_recursive': False,
      }
      with adhoc_imports.adhoc(**adhoc_kwargs):
        for module in modules_to_update:
          importlib.import_module(module)

      # Update globals in user namespace with reloaded modules
      ip = IPython.get_ipython()
      kernel_globals = ip.kernel.shell.user_ns

      for name, info in self._globals_to_update.items():
        if info.name in modules_to_update and id(
            kernel_globals.get(name)
        ) == id(info.instance):
          reloaded_module = sys.modules[info.name]
          self.print(f'Overwrting {name} to new module {info.name}')
          kernel_globals[name] = reloaded_module
          self._globals_to_update[name] = dataclasses.replace(
              info, instance=reloaded_module
          )
        else:
          # If the global was updated previously
          self.print(f'Ignoring {name} (was overwritten)')


def _get_last_module_update(module_name: str) -> int | None:
  """Get the last update for one module."""
  module = sys.modules.get(module_name, None)
  if module is None:
    return None
  if module.__name__ == '__main__':
    return None

  module_file = getattr(module, '__file__', None)
  if not module_file:
    return None

  module_file = epath.Path(module_file)

  try:
    return module_file.stat().mtime
  except OSError:
    return None
