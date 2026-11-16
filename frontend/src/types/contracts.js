/** @typedef {{id:number,hour:string,pressure:number,flow:number,temperature:number,machines:number,sensor_noise:number,kwh:number,note:string}} Sample */
/** @typedef {{id:number,name:string,features:string[],alphas:number[],state:string,result:object,error:string}} Run */
/** @typedef {{id:number,run_id:number,title:string,finding:string,action:string,status:string}} Review */
/** @typedef {{key:string,features:string[],rank:number,cv_rmse:number,validation_rmse:number,selected_alpha:number,intercept_original:number,coefficients:{feature:string,standardized:number,original_unit:number}[],scaler_mean:number[],scaler_scale:number[]}} FamilyMember */
/** @typedef {{id:number,name:string,features:string[],alphas:number[],state:string,result:object|null,error:string,created:string}} Family */
/** @typedef {{id:number,family_id:number,batch_key:string,state:string,result:object|null,created:string}} Batch */
/** @typedef {{line:number,hour:string,features:object,kwh:number|null,label:string,note:string,provided_features:string[],family_missing_features:string[],chosen_features:string[],member_key:string,member_rank:number,training_cv_rmse:number,prediction:number,actual:number|null,residual:number|null}} BatchRow */
