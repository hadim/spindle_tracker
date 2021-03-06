# -*- coding: utf-8 -*-

from __future__ import unicode_literals
from __future__ import division
from __future__ import absolute_import
from __future__ import print_function

import logging
log = logging.getLogger(__name__)

import numpy as np

from ...utils import print_progress

from ..matrix import CostMatrix
from ..cost_function import AbstractCostFunction
from ..cost_function.brownian import BrownianLinkCostFunction
from ..cost_function.diagonal import DiagonalCostFunction
from ..cost_function.directed import BasicDirectedLinkCostFunction

from . import AbstractSolver

__all__ = []


class ByFrameSolver(AbstractSolver):
    """

    Parameters
    ----------
    trajs : :class:`pandas.DataFrame`
    cost_functions : list of list
    """
    def __init__(self, trajs, cost_functions, coords=['x', 'y', 'z']):

        super(self.__class__, self).__init__(trajs)

        self.t_in = 0
        self.t_out = 0

        self.coords = coords

        self.trajs.check_trajs_df_structure(index=['t_stamp', 'label'],
                                            columns=['t'] + coords)

        self.link_cf = cost_functions['link']
        self.check_cost_function_type(self.link_cf, AbstractCostFunction)

        self.birth_cf = cost_functions['birth']
        self.check_cost_function_type(self.birth_cf, AbstractCostFunction)

        self.death_cf = cost_functions['death']
        self.check_cost_function_type(self.death_cf, AbstractCostFunction)

        self.max_assigned_cost = self.death_cf.context['cost']

    @classmethod
    def for_brownian_motion(cls, trajs,
                            max_speed,
                            penalty=1.05,
                            coords=['x', 'y', 'z']):
        """

        Parameters
        ----------
        trajs : :class:`spindle_tracker.trajectories.Trajectories`
        max_speed : float
            Maximum objects velocity
        penalty : float
        coords : list
            Which columns to choose in trajs when computing distances.

        Examples
        --------
        >>> true_trajs = Trajectories(data.brownian_trajectories_generator())
        >>>
        >>> # Remove labels
        >>> true_trajs.relabel(np.arange(len(true_trajs)))
        >>>
        >>> solver = ByFrameSolver.for_brownian_motion(true_trajs, max_speed=5, penalty=2.)
        >>> new_trajs = solver.track()
        2014:INFO:by_frame_solver: Initiating frame by frame tracking.
        2014:INFO:by_frame_solver: Frame by frame tracking done. 5 segments found (500 before).
        """
        guessed_cost = np.float(max_speed ** 2) * penalty
        diag_context = {'cost': guessed_cost}
        diag_params = {'penalty': penalty, 'coords': coords}

        link_cost_func = BrownianLinkCostFunction(parameters={'max_speed': max_speed,
                                                              'coords': coords})
        birth_cost_func = DiagonalCostFunction(context=diag_context,
                                               parameters=diag_params)
        death_cost_func = DiagonalCostFunction(context=diag_context,
                                               parameters=diag_params)

        cost_functions = {'link': link_cost_func,
                          'birth': birth_cost_func,
                          'death': death_cost_func}

        return cls(trajs, cost_functions, coords=coords)

    @classmethod
    def for_directed_motion(cls, trajs,
                            max_speed,
                            penalty=1.05,
                            past_traj_time=10,
                            smooth_factor=0,
                            interpolation_order=1,
                            coords=['x', 'y', 'z']):
        """Link objects according to their distance found in trajectories frame by frame.

        Parameters
        ----------
        trajs : :class:`spindle_tracker.trajectories.Trajectories`
        max_speed : float
            Maximum objects velocity
        penalty : float
        past_traj_time : float
            Time during which the tracker can make a gap close. Above this time all gap
            close event will discarded.
        smooth_factor : float
            Smoothing condition used in :func:`scipy.interpolate.splrep`
        interpolation_order : int
            The order of the spline fit. See :func:`scipy.interpolate.splrep`
        coords : list
            Which columns to choose in trajs when computing distances.
        """

        parameters = {'max_speed': max_speed,
                      'past_traj_time': past_traj_time,
                      'smooth_factor': smooth_factor,
                      'interpolation_order': interpolation_order,
                      'coords': coords}

        guessed_cost = 20 * penalty
        diag_context = {'cost': guessed_cost}
        diag_params = {'penalty': penalty}
        link_context = {'trajs': trajs}

        link_cost_func = BasicDirectedLinkCostFunction(parameters=parameters,
                                                       context=link_context)

        birth_cost_func = DiagonalCostFunction(context=diag_context,
                                               parameters=diag_params)
        death_cost_func = DiagonalCostFunction(context=diag_context,
                                               parameters=diag_params)

        cost_functions = {'link': link_cost_func,
                          'birth': birth_cost_func,
                          'death': death_cost_func}

        return cls(trajs, cost_functions, coords=coords)

    @property
    def blocks_structure(self):
        return [[self.link_cf.mat, self.death_cf.mat],
                [self.birth_cf.mat, None]]

    @property
    def pos_in(self):
        return self.trajs.loc[self.t_in]

    @property
    def pos_out(self):
        return self.trajs.loc[self.t_out]

    def track(self, progress_bar=False, progress_bar_out=None):
        """

        Returns
        -------
        self.trajs : :class:`pandas.DataFrame`
        progress_bar : bool
            Display progress bar
        progress_bar_out : OutStream
            For testing purpose only
        """

        log.info('Initiating frame by frame tracking.')

        old_labels = self.trajs.index.get_level_values('label').values
        self.trajs['new_label'] = old_labels.astype(np.float)
        ts_in = self.trajs.t_stamps[:-1]
        ts_out = self.trajs.t_stamps[1:]

        n_labels_before = len(self.trajs.labels)

        n = len(ts_in)
        for i, (t_in, t_out) in enumerate(zip(ts_in, ts_out)):
            if progress_bar:
                progress = i / n * 100
                message = "t_in : {} | t_out {}".format(t_in, t_out)
                print_progress(progress, message=message, out=progress_bar_out)

            self.one_frame(t_in, t_out)

        if progress_bar:
            print_progress(-1)

        self.relabel_trajs()

        n_labels_after = len(self.trajs.labels)
        mess = 'Frame by frame tracking done. {} segments found ({} before).'
        log.info(mess.format(n_labels_after, n_labels_before))
        return self.trajs

    def one_frame(self, t_in, t_out):
        """

        Parameters
        ----------
        t_in : int
        t_out : int
        """

        self.t_in = t_in
        self.t_out = t_out

        pos_in = self.pos_in
        pos_out = self.pos_out

        self.link_cf.context['pos_in'] = pos_in
        self.link_cf.context['pos_out'] = pos_out
        self.link_cf.get_block()

        self.birth_cf.context['objects'] = pos_out
        self.birth_cf.get_block()

        self.death_cf.context['objects'] = pos_in
        self.death_cf.get_block()

        self.cm = CostMatrix(self.blocks_structure)
        self.cm.solve()
        self.assign()

    def assign(self):
        """
        """

        row_shapes, col_shapes = self.cm.get_shapes()
        last_in_link = row_shapes[0]
        last_out_link = col_shapes[0]

        new_labels_in = self.trajs.loc[self.t_in]['new_label'].values
        new_labels_out = np.arange(last_out_link)

        for idx_out, idx_in in enumerate(self.cm.out_links[:last_out_link]):
            if idx_in >= last_in_link:
                # new segment
                new_label = self.trajs['new_label'].max() + 1.
            else:
                # assignment
                new_label = new_labels_in[idx_in]
                self._update_max_assign_cost(self.cm.mat[idx_in, idx_out])

            new_labels_out[idx_out] = new_label
            self.trajs.loc[self.t_out, 'new_label'] = new_labels_out
            # The line below looks much slower than the two lines above
            # self.trajs.loc[self.t_out, 'new_label'].iloc[idx_out] = new_label

    def _update_max_assign_cost(self, cost):
        """
        """

        if cost > self.max_assigned_cost:
            self.max_assigned_cost = cost
            new_b_cost = self.max_assigned_cost * self.birth_cf.parameters['penalty']
            new_d_cost = self.max_assigned_cost * self.death_cf.parameters['penalty']
            self.birth_cf.context['cost'] = new_b_cost
            self.death_cf.context['cost'] = new_d_cost
