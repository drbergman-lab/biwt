"""
Default PhysiCell XML snippets for each top-level config section.

These are the baseline values BIWT inserts when generating a new
PhysiCell_settings.xml from scratch.  Studio uses its own live XML;
these defaults are only relevant when BIWT operates standalone.
"""

xml_defaults = {

    "domain": """
            <x_min>-500</x_min>
            <x_max>500</x_max>
            <y_min>-500</y_min>
            <y_max>500</y_max>
            <z_min>-10</z_min>
            <z_max>10</z_max>
            <dx>20</dx>
            <dy>20</dy>
            <dz>20</dz>
            <use_2D>true</use_2D>
    """,

    "overall": """
            <max_time units="min">7200</max_time>
            <time_units>min</time_units>
            <space_units>micron</space_units>
            <dt_diffusion units="min">0.01</dt_diffusion>
            <dt_mechanics units="min">0.1</dt_mechanics>
            <dt_phenotype units="min">6</dt_phenotype>
    """,

    "parallel": """
            <omp_num_threads>4</omp_num_threads>
    """,

    "save": """
            <folder>output</folder>
            <full_data>
                <interval units="min">60</interval>
                <enable>true</enable>
            </full_data>
            <SVG>
                <interval units="min">60</interval>
                <enable>true</enable>
                <plot_substrate enabled="false" limits="false">
                    <substrate>substrate</substrate>
                    <min_conc />
                    <max_conc />
                </plot_substrate>
            </SVG>
            <legacy_data>
                <enable>false</enable>
            </legacy_data>
    """,

    "options": """
            <legacy_random_points_on_sphere_in_divide>false</legacy_random_points_on_sphere_in_divide>
            <virtual_wall_at_domain_edge>true</virtual_wall_at_domain_edge>
            <disable_automated_spring_adhesions>false</disable_automated_spring_adhesions>
            <random_seed>0</random_seed>
        """,

    "microenvironment_setup": """
            <variable name="substrate" units="dimensionless" ID="0">
                <physical_parameter_set>
                    <diffusion_coefficient units="micron^2/min">100000.0</diffusion_coefficient>
                    <decay_rate units="1/min">10</decay_rate>
                </physical_parameter_set>
                <initial_condition units="mmHg">0</initial_condition>
                <Dirichlet_boundary_condition units="mmHg" enabled="False">0</Dirichlet_boundary_condition>
                <Dirichlet_options>
                    <boundary_value ID="xmin" enabled="False">0</boundary_value>
                    <boundary_value ID="xmax" enabled="False">0</boundary_value>
                    <boundary_value ID="ymin" enabled="False">0</boundary_value>
                    <boundary_value ID="ymax" enabled="False">0</boundary_value>
                    <boundary_value ID="zmin" enabled="False">0</boundary_value>
                    <boundary_value ID="zmax" enabled="False">0</boundary_value>
                </Dirichlet_options>
            </variable>
            <options>
                <calculate_gradients>true</calculate_gradients>
                <track_internalized_substrates_in_each_agent>true</track_internalized_substrates_in_each_agent>
                <initial_condition type="matlab" enabled="false">
                    <filename>./config/initial.mat</filename>
                </initial_condition>
                <dirichlet_nodes type="matlab" enabled="false">
                    <filename>./config/dirichlet.mat</filename>
                </dirichlet_nodes>
            </options>
        """,

    "initial_conditions": """
            <cell_positions type="csv" enabled="true">
                <folder>./config</folder>
                <filename>cells.csv</filename>
            </cell_positions>
    """,

    "cell_rules": """
            <rulesets>
                <ruleset protocol="CBHG" version="3.0" format="csv" enabled="false">
                    <folder>./config</folder>
                    <filename>rules0.csv</filename>
                </ruleset>
            </rulesets>
            <settings />
    """,

    "user_parameters": """
            <number_of_cells type="int" units="none" description="initial number of cells (for each cell type)">5</number_of_cells>
    """,
}
