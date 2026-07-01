package com.yollo.TravelMate.util;

public class VectorUtil {

	public static String toVectorString(float [] vector) {
		
		StringBuilder sb = new StringBuilder();
		
		sb.append("[");
		
		for(int i = 0 ; i<vector.length;++i) {
			float feature = vector[i];
			if(i != 0) sb.append(",");
			sb.append(feature);
				
		}
		
		sb.append("]");
		
		return sb.toString();
		
	}
	
	
}
