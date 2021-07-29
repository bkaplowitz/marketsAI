clear all

% State which model
model = "capital_planner_1hh";
path = '/Users/matiascovarrubias/Documents/universidad/NYU/Research/Repositories/marketsAI/marketsai/Econ_algos/' + model;
script = 'iter_'+model;

%add path
addpath path;

% run iterations
ItrRslt = eval(script);
% Policy grid (I want a matrix with K rows and N_shocks as columns
K = ItrRslt.var_state.K; % 1*101
s = ItrRslt.var_policy.s; % 2*101

grid = [K',s'];
%transpose both and a

%to do:
% two shocks and parameteres of simulations. 
% take it to python and from there create a compute_action that takes as
% extra input the policy grid that 




