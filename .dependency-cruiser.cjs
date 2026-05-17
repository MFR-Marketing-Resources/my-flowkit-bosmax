module.exports = {
	forbidden: [
		{
			name: "no-circular",
			severity: "error",
			from: {},
			to: { circular: true },
		},
	],
	options: {
		tsConfig: {
			fileName: "dashboard/tsconfig.app.json",
		},
		enhancedResolveOptions: {
			extensions: [".ts", ".tsx", ".js", ".jsx", ".json"],
		},
		tsPreCompilationDeps: true,
		doNotFollow: {
			path: "node_modules",
		},
		includeOnly: "^dashboard/src",
		exclude: {
			path: "^(node_modules|dashboard/dist|dashboard/node_modules)",
		},
	},
};
